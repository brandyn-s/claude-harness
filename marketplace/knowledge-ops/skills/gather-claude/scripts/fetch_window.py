#!/usr/bin/env python3
"""Fetch every Step 4-8b source for one gather-claude window, in parallel.

WHY THIS EXISTS
    Steps 4, 4b, 5-successor, 7, 7b, 8 and 8b are ~30 INDEPENDENT `gh` and
    `curl` calls. Run conversationally they go one at a time, and the 2026-08-21
    run spent the majority of its wall clock waiting on them in sequence. They
    share no state, so they parallelize exactly.

    It also removes three recurring correctness hazards that a hand-run sweep
    keeps reintroducing:

    1. TRUNCATION BLINDNESS. A label sweep returning `rows == limit` is an
       INCOMPLETE set, but the documented health test (max issue number vs the
       window's newest) only catches labeling LAG. On 2026-08-21 all 8 sweeps
       passed the max-number test while all 8 were capped at 50. This script
       flags `rows == limit` per task, so truncation is impossible to miss.
    2. FETCH PIPES. Every fetch lands in a FILE; nothing is piped into an
       interpreter or a filter, so neither `bash-security-guard
       [exfiltration-guard]` nor `bash-tail-buffering-guard` can fire.
    3. SILENT CHANNEL OMISSION. Every task appears in the manifest with its own
       exit code and byte count, so a failed channel is visibly failed rather
       than indistinguishable from a channel nobody fetched (the ambiguity
       Step 14b's narrative exists to remove).

OUTPUT
    <out>/<task>.json|.txt   one file per task, raw
    <out>/manifest.json      task -> {rc, bytes, truncated, cmd}
    stdout                   human table, TRUNCATED and FAILED called out
    baselines dir            dated docs-page baseline + diff vs previous
                             (Step 8's mandated file — automated 2026-08-22
                             after zero runs ever persisted it by hand)

USAGE
    python3 fetch_window.py --since 2026-08-12 --out /tmp/claude/gc-run
    python3 fetch_window.py --since 2026-08-12 --platform macos --jobs 8
    python3 fetch_window.py --summary --out /tmp/claude/gc-run   # re-print table
    # census-count task: exact search-API total_count for the window — the
    # denominator census-unlabeled cannot state once it hits the row cap.

    --platform MUST match the host (`uname`): a stale platform label silently
    covers a host we do not run. Defaults from `uname`.

Read-only. Requires `gh` (authenticated) and `curl`.
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

REPO = "anthropics/claude-code"
LABEL_LIMIT = 100          # in-window census; see references/github-track-queries.md
KEYWORD_LIMIT = 50         # was 14: 8 of 9 keyword sweeps hit 14 on a 9-day window
MAX_LIMIT = 400            # escalation ceiling; GitHub search truncates near here


def _with_limit(argv, n):
    """Copy argv with the value after --limit replaced by n."""
    out = list(argv)
    try:
        out[out.index("--limit") + 1] = str(n)
    except (ValueError, IndexError):
        pass
    return out

LABEL_SETS = [
    ("label-platform", 'label:bug label:"platform:{platform}"'),
    ("label-hooks", "label:bug label:area:hooks"),
    ("label-agents", "label:bug label:area:agents"),
    ("label-mcp", "label:bug label:area:mcp"),
    ("label-regression", "label:regression"),
    ("label-data-loss", "label:data-loss"),
    ("label-bedrock", "label:api:bedrock"),
    ("label-security", "label:area:security"),
]

KEYWORDS = [
    "hook", "subagent nesting", "worktree", "transcript", "skill",
    "permission deny", "sandbox bash", "managed settings", "session start",
]

RELEASE_REPOS = [
    ("rel-claude-code", REPO, 20),
    ("rel-agent-sdk-py", "anthropics/claude-agent-sdk-python", 10),
    ("rel-agent-sdk-ts", "anthropics/claude-agent-sdk-typescript", 10),
    ("rel-api-sdk-py", "anthropics/anthropic-sdk-python", 10),
    ("rel-api-sdk-ts", "anthropics/anthropic-sdk-typescript", 10),
    ("rel-mcp-spec", "modelcontextprotocol/modelcontextprotocol", 5),
]

CURL_TASKS = [
    ("docs-llms", "https://code.claude.com/docs/llms.txt", "txt"),
    ("doc-changelog", "https://code.claude.com/docs/en/changelog.md", "txt"),
    ("doc-hooks", "https://code.claude.com/docs/en/hooks.md", "txt"),
    ("doc-skills", "https://code.claude.com/docs/en/skills.md", "txt"),
    ("doc-settings", "https://code.claude.com/docs/en/settings.md", "txt"),
    ("doc-subagents", "https://code.claude.com/docs/en/sub-agents.md", "txt"),
    ("doc-mcp", "https://code.claude.com/docs/en/mcp.md", "txt"),
    ("platform-release-notes",
     "https://platform.claude.com/docs/en/release-notes/overview.md", "txt"),
    ("model-deprecations",
     "https://platform.claude.com/docs/en/about-claude/model-deprecations.md", "txt"),
    ("bedrock-rss", "https://aws.amazon.com/about-aws/whats-new/recent/feed/", "txt"),
    ("status", "https://status.claude.com/api/v2/summary.json", "json"),
    ("npm-dist-tags",
     "https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags", "json"),
    # Desktop-3P (SKILL.md Step 8b item 5). ADDED 2026-08-30 — these were
    # REQUIRED by the skill but had no task here, so the manifest reported
    # "0 failed" while the channel was never fetched at all. That run found 5
    # in-window releases in it, including the v1.40609.0 deprecation wave with a
    # hard 2026-10-07 cut-off affecting keys deployed through any MDM. An
    # omitted channel is indistinguishable from an empty one; that is the bug.
    # NOTE the host: these live on claude.com/docs/third-party/, NOT
    # code.claude.com — the code.claude.com spellings 404.
    ("desktop-3p-changelog",
     "https://claude.com/docs/third-party/claude-desktop/configuration-changelog.md", "txt"),
    ("desktop-3p-m365",
     "https://claude.com/docs/third-party/claude-desktop/connectors-m365.md", "txt"),
]


def host_platform():
    s = platform.system().lower()
    return {"darwin": "macos", "windows": "windows"}.get(s, "linux")


def build_tasks(since, plat):
    """Return [(name, argv, ext, limit_or_None)]. limit set => truncation-checkable."""
    tasks = []
    for name, sel in LABEL_SETS:
        q = f"{sel.format(platform=plat)} created:>={since}"
        tasks.append((name, [
            "gh", "issue", "list", "--repo", REPO, "--state", "open",
            "--limit", str(LABEL_LIMIT), "--json", "number,title,createdAt,labels",
            "--search", q,
        ], "json", LABEL_LIMIT))

    for kw in KEYWORDS:
        slug = "kw-" + kw.replace(" ", "-")
        tasks.append((slug, [
            "gh", "issue", "list", "--repo", REPO, "--state", "open",
            "--limit", str(KEYWORD_LIMIT), "--json", "number,title,createdAt",
            "--search", f"{kw} created:>={since}",
        ], "json", KEYWORD_LIMIT))

    # Unlabeled in-window census — labeling lag makes this mandatory.
    tasks.append(("census-unlabeled", [
        "gh", "issue", "list", "--repo", REPO, "--state", "open",
        "--limit", "100", "--json", "number,title,createdAt",
        "--search", f"created:>={since}",
    ], "json", 100))
    # Exact census denominator via the search API's total_count: one call,
    # immune to the row-fetch escalation ceiling (census-unlabeled has hit the
    # MAX_LIMIT cap on every run to date — the true magnitude was unknowable
    # from a capped row set).
    tasks.append(("census-count", [
        "gh", "api", "-X", "GET", "search/issues",
        "-f", f"q=repo:{REPO} is:issue created:>={since}",
        "--jq", ".total_count",
    ], "txt", None))

    tasks.append(("advisories-firstparty", [
        "gh", "api", f"repos/{REPO}/security-advisories",
    ], "json", None))
    tasks.append(("advisories-sdk", [
        "gh", "api", "/advisories?affects=anthropic",
    ], "json", None))
    tasks.append(("merged-prs", [
        "gh", "pr", "list", "--repo", REPO, "--state", "merged", "--limit", "50",
        "--json", "number,title,mergedAt", "--search", f"merged:>={since}",
    ], "json", 50))
    tasks.append(("changelog-b64", [
        "gh", "api", f"repos/{REPO}/contents/CHANGELOG.md", "--jq", ".content",
    ], "txt", None))

    for name, repo, lim in RELEASE_REPOS:
        tasks.append((name, [
            "gh", "release", "list", "--repo", repo, "--limit", str(lim),
            "--json", "tagName,name,publishedAt",
        ], "json", None))

    for name, url, ext in CURL_TASKS:
        # -L is mandatory: status.claude.com 302s, and a redirect stub parses as
        # malformed JSON rather than as a redirect.
        tasks.append((name, ["curl", "-sS", "-L", url], ext, None))

    return tasks


def run_task(task, out_dir):
    name, argv, ext, limit = task
    path = out_dir / f"{name}.{ext}"
    # AUTO-ESCALATION. A FIXED --limit is what made truncation invisible: measured
    # 2026-08-21, 12 of 40 sources came back at exactly their limit, including 8 of
    # the 9 architecture-keyword sweeps at the documented 14. Raising the constant
    # only moves the cliff, so instead: when rows == limit, re-fetch at 2x and keep
    # doubling until the result stops filling the limit or MAX_LIMIT is hit. A set
    # that is still full at MAX_LIMIT stays flagged truncated — escalation reports
    # the ceiling, it does not paper over it.
    attempts, cur = [], limit
    while True:
        run_argv = argv if cur == limit else _with_limit(argv, cur)
        try:
            res = subprocess.run(run_argv, capture_output=True, text=True, timeout=180)
            out = res.stdout
            rc, err = res.returncode, (res.stderr or "").strip()[:200]
        except subprocess.TimeoutExpired:
            out, rc, err = "", 124, "timeout after 180s"

        rows = None
        if ext == "json" and rc == 0:
            try:
                parsed = json.loads(out or "null")
                if isinstance(parsed, list):
                    rows = len(parsed)
            except json.JSONDecodeError:
                err = err or "stdout is not valid JSON"

        path.write_text(out, encoding="utf-8")
        attempts.append(cur)
        if cur is None or rows is None:
            break                      # no limit to escalate, or no row count
        if rows < cur or cur >= MAX_LIMIT:
            break                      # room to spare, or ceiling reached
        cur = min(cur * 2, MAX_LIMIT)

    last = attempts[-1]
    truncated = None
    if last is not None and rows is not None:
        truncated = rows >= last

    return name, {
        "rc": rc, "bytes": path.stat().st_size, "rows": rows,
        "truncated": truncated, "limit_used": attempts[-1],
        "escalations": attempts[1:], "stderr": err,
        "cmd": " ".join(argv), "file": str(path),
    }


def print_summary(manifest, tasks_total=None):
    """Human table from a manifest dict. Also the --summary re-print path, so
    no run ever needs an ad-hoc manifest reader (2026-08-22: an inline reader
    was guard-blocked, then mis-iterated .values() and lost the task names)."""
    failed = [n for n, i in manifest.items() if i["rc"] != 0]
    trunc = [n for n, i in manifest.items() if i.get("truncated")]
    empty = [n for n, i in manifest.items() if i["rc"] == 0 and i["bytes"] == 0]

    print(f"\n{'task':28} {'rc':>3} {'bytes':>9} {'rows':>5}  note")
    for name in sorted(manifest):
        i = manifest[name]
        note = []
        if i["rc"] != 0:
            note.append(f"FAILED: {i['stderr']}")
        if i.get("escalations"):
            note.append("escalated " + "->".join(str(x) for x in i["escalations"]))
        if i.get("truncated"):
            note.append(f"TRUNCATED at limit {i.get('limit_used')} "
                        f"(set is INCOMPLETE even after escalation)")
        if i["rc"] == 0 and i["bytes"] == 0:
            note.append("empty body")
        rows = "" if i["rows"] is None else i["rows"]
        print(f"{name:28} {i['rc']:>3} {i['bytes']:>9} {rows:>5}  {'; '.join(note)}")

    total = tasks_total if tasks_total is not None else len(manifest)
    print(f"\n{total} tasks | {len(failed)} failed | {len(trunc)} truncated "
          f"| {len(empty)} empty")
    if trunc:
        print("TRUNCATED sets must be re-fetched at a higher --limit or narrowed "
              "before any coverage claim: " + ", ".join(sorted(trunc)))
    if failed:
        print("FAILED sources are UNKNOWN, not empty — record them in the Sources "
              "Log: " + ", ".join(sorted(failed)))
    return failed


def persist_docs_baseline(out_dir, baseline_dir, today):
    """Extract the docs page set from docs-llms.txt, write a dated baseline,
    and diff against the newest previous baseline.

    Step 8 has mandated this file since 2026-07-05 and NO run ever persisted
    it, so the page-set diff had never once been derivable (measured
    2026-08-22: zero baseline files existed). Automating it here removes the
    dead-letter step. A missing/unwritable baseline dir degrades gracefully.
    """
    import re as _re
    src = out_dir / "docs-llms.txt"
    if not src.exists():
        print("docs baseline: docs-llms.txt absent, skipped")
        return
    pages = sorted(set(_re.findall(r"docs/en/[A-Za-z0-9/_-]+\.md", src.read_text(encoding="utf-8"))))
    if not pages:
        print("docs baseline: 0 pages extracted, skipped (inventory format changed?)")
        return
    try:
        bdir = Path(baseline_dir).expanduser()
        bdir.mkdir(parents=True, exist_ok=True)
        target = bdir / f"claude-docs-pages-{today}.txt"
        # Same-date no-clobber: a second run on the same day must diff against
        # the first run's file BEFORE overwriting it, or the intra-day change
        # is silently destroyed (2026-08-22: run-b overwrote run-a's baseline
        # and then reported "no previous baseline").
        prior_same_day = target.read_text(encoding="utf-8").splitlines() if target.exists() else None
        prev = sorted(p for p in bdir.glob("claude-docs-pages-*.txt")
                      if p.name != target.name)
        if not prev:
            # Origin fallback: this checkout may be BEHIND the remote that
            # holds the previous baseline (2026-08-22: baseline existed on
            # origin/main, local dir was empty -> false "first baseline").
            fetched = _origin_previous_baseline(bdir, today)
            if fetched is not None:
                prev = [fetched]
        target.write_text("\n".join(pages) + "\n", encoding="utf-8")
        print(f"docs baseline: {len(pages)} pages -> {target}")
        old_pages = None
        label = None
        if prior_same_day is not None:
            old_pages, label = set(prior_same_day), f"{target.name} (same-date, earlier run)"
        elif prev:
            old_pages, label = set(prev[-1].read_text(encoding="utf-8").splitlines()), prev[-1].name
            if prev[-1].name.startswith(".origin-"):
                prev[-1].unlink(missing_ok=True)  # recovered copy, not a real local baseline
        if old_pages is not None:
            new = set(pages)
            added, removed = sorted(new - old_pages), sorted(old_pages - new)
            print(f"docs page-set diff vs {label}: +{len(added)} / -{len(removed)}")
            for p in added:
                print(f"  + {p}")
            for p in removed:
                print(f"  - {p}  <- REMOVED page, high-signal")
        else:
            print("docs baseline: no previous baseline anywhere (local dir and "
                  "origin) — diff not derivable this run (first persisted baseline)")
    except OSError as e:
        print(f"docs baseline: NOT persisted ({e}) — record in Sources Log")


def _origin_previous_baseline(bdir, today):
    """Newest pre-today baseline from origin/<default>, or None.

    Reads it via `git show` into a temp-named Path-like object is overkill;
    we materialize it under the out-of-tree name .origin-<file> so the glob
    for local baselines never picks it up on later runs."""
    try:
        root = subprocess.run(["git", "-C", str(bdir), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=10)
        if root.returncode != 0:
            return None
        top = root.stdout.strip()
        rel = str(bdir.resolve().relative_to(Path(top).resolve()))
        # ls-tree pathspecs are cwd-relative: run from the toplevel, or a
        # bdir-cwd invocation silently matches nothing (measured 2026-08-22).
        ls = subprocess.run(["git", "-C", top, "ls-tree", "--name-only",
                             "origin/main", f"{rel}/"],
                            capture_output=True, text=True, timeout=15)
        names = sorted(n for n in ls.stdout.split()
                       if re.match(rf"{re.escape(rel)}/claude-docs-pages-.*\.txt$", n)
                       and not n.endswith(f"claude-docs-pages-{today}.txt"))
        if not names:
            return None
        show = subprocess.run(["git", "-C", top, "show", f"origin/main:{names[-1]}"],
                              capture_output=True, text=True, timeout=15)
        if show.returncode != 0:
            return None
        tmp = bdir / f".origin-{Path(names[-1]).name}"
        tmp.write_text(show.stdout, encoding="utf-8")
        print(f"docs baseline: previous baseline recovered from origin/main "
              f"({Path(names[-1]).name}) — local dir had none (checkout behind?)")
        return tmp
    except (OSError, subprocess.SubprocessError, ValueError):
        return None




def report_issue_overlap(out_dir, manifest, report_path):
    """Split fetched issue numbers into ALREADY-COVERED vs FRESH, and bucket
    the [cyber] classifier-FP flood into one counted line.

    Same-day/overlapping windows re-surface numbers the previous run already
    processed (2026-08-22: 6 of the window's high-signal numbers were in that
    morning's report and had to be hand-grepped). The [cyber] bucket exists
    because classifier-FP reports dominate area:security by volume (12/20 on
    2026-08-22) and are a wave to count, not rows to triage individually."""
    all_issues = {}   # number -> title
    for name, info in manifest.items():
        f = Path(info["file"])
        if not f.suffix == ".json" or not f.exists():
            continue
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and "number" in r and "title" in r:
                    all_issues[r["number"]] = r["title"]
    if not all_issues:
        return
    cyber = sorted(n for n, ti in all_issues.items() if "[cyber]" in ti.lower())
    if cyber:
        print(f"[cyber] classifier-FP bucket: {len(cyber)} of {len(all_issues)} "
              f"in-window issues ({' '.join(f'#{n}' for n in cyber)}) — count the "
              f"wave, do not triage individually")
    if not report_path:
        return
    try:
        report = Path(report_path).expanduser().read_text(encoding="utf-8")
    except OSError as e:
        print(f"dedupe: report unreadable ({e}) — overlap not derivable")
        return
    known = {int(n) for n in re.findall(r"#(\d{3,7})\b", report)}
    covered = sorted(n for n in all_issues if n in known)
    fresh = sorted(n for n in all_issues if n not in known and n not in cyber)
    print(f"dedupe vs {Path(report_path).name}: {len(covered)} already covered "
          f"({' '.join(f'#{n}' for n in covered) or 'none'})")
    print(f"FRESH (triage these): {len(fresh)} "
          f"({' '.join(f'#{n}' for n in fresh) or 'none'})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="window start, YYYY-MM-DD")
    ap.add_argument("--out", default="/tmp/claude/gc-run")
    ap.add_argument("--platform", default=None,
                    help="macos|windows|linux (defaults to this host)")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--summary", action="store_true",
                    help="re-print the table from an existing manifest and exit")
    ap.add_argument("--baseline-dir",
                    default="~/Documents/knowledge-base/research/baselines",
                    help="where dated docs-page baselines are persisted")
    ap.add_argument("--get", metavar="TASK",
                    help="print the named task's output file path from the "
                         "manifest and exit (kills extension-guessing: "
                         "npm-dist-tags is .json, changelog-b64 is raw base64 "
                         ".txt, status is .json)")
    ap.add_argument("--dedupe-against", metavar="REPORT",
                    help="path to the prior intelligence report; after the "
                         "fetch, split every issue-list task's numbers into "
                         "ALREADY-COVERED (mentioned in the report) vs FRESH, "
                         "so overlapping/same-day windows need no hand-grep")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if args.get:
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        if args.get not in manifest:
            print(f"no such task: {args.get}; tasks: {', '.join(sorted(manifest))}",
                  file=sys.stderr)
            return 1
        print(manifest[args.get]["file"])
        return 0
    if args.summary:
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        failed = print_summary(manifest)
        return 1 if failed else 0
    if not args.since:
        ap.error("--since is required (unless --summary)")

    plat = args.platform or host_platform()
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks(args.since, plat)

    print(f"fetching {len(tasks)} sources for window >= {args.since} "
          f"(platform:{plat}, {args.jobs} parallel)", file=sys.stderr)

    manifest = {}
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for name, info in pool.map(lambda t: run_task(t, out_dir), tasks):
            manifest[name] = info

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    failed = print_summary(manifest, tasks_total=len(tasks))
    persist_docs_baseline(out_dir, args.baseline_dir,
                          datetime.date.today().isoformat())
    report_issue_overlap(out_dir, manifest, args.dedupe_against)
    print(f"manifest: {out_dir / 'manifest.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
