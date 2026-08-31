#!/usr/bin/env python3
"""Pre-write budget for a knowledge-base entry: predict what `kb.py check` will say.

WHY THIS EXISTS: /capture drafts an entry, writes it, and only then runs
`kb.py check` — so every structural limit is discovered AFTER the prose is
finished, and the fix is a rewrite. On 2026-07-28 one capture run wrote three
entries and had all three rejected (3,525c / 3,601c / 3,115c against the
3,000c hard limit), then had to retro-fit a `## Current understanding` section
because the appends silently crossed the 8-dated-entry threshold. All four
facts were computable before the first Write: the drafted text was in hand and
the target pages had already been read.

This tool answers, for a drafted entry:
  - what retrieval chunk(s) will it create, and are any over the hard limit?
  - does appending it cross the stage threshold (seedling/budding/evergreen)?
  - does it cross 8 dated entries, requiring `## Current understanding`?
  - if that section exists, is it itself over the chunk limit?

It deliberately mirrors kb.py's own chunking rule (see CHUNK NOTE below)
rather than approximating it, because an approximation that disagrees with the
checker is worse than no tool: it would greenlight a draft the gate rejects.

Usage:
  kb-entry-budget.py <topic-slug> --entry-file <draft.md>
  kb-entry-budget.py <topic-slug> --entry-file <draft.md> --json
  kb-entry-budget.py <topic-slug> --kb-root <checkout>
  kb-entry-budget.py <topic-slug>            # audit the page as it stands
  kb-entry-budget.py --self-check            # verify limits still match kb.py

When invoked inside a knowledge-base Git worktree, the tool reads that
worktree's `tools/kb.py` and `topics/`. Otherwise it falls back to the canonical
`~/Documents/knowledge-base` checkout.

Exit codes:
  0  budget OK (warnings may still print)
  1  a `kb.py check` failure is already guaranteed — restructure before writing
  2  usage / topic not found
  3  kb.py limits could not be read (tool may be stale — do not trust it)
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

DEFAULT_KB_ROOT = pathlib.Path.home() / "Documents" / "knowledge-base"

DATED_H2 = re.compile(r"^## .*\(\d{4}-\d{2}-\d{2}\)", re.MULTILINE)
STRUCTURAL = re.compile(r"^(#{2,3}) (.+?)\s*$", re.MULTILINE)


def resolve_kb_root(
    cwd: pathlib.Path | None = None,
    explicit: str | None = None,
) -> pathlib.Path:
    """Prefer the invoking knowledge-base worktree, then the canonical clone."""
    if explicit:
        return pathlib.Path(explicit).expanduser().resolve()
    current = (cwd or pathlib.Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(current), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result and result.returncode == 0:
        candidate = pathlib.Path(result.stdout.strip()).resolve()
        if (candidate / "tools" / "kb.py").is_file() and (
            candidate / "topics"
        ).is_dir():
            return candidate
    return DEFAULT_KB_ROOT


def read_limits(kb_root: pathlib.Path | None = None):
    """Read the limits from kb.py itself.

    Hardcoding 3000/8 here would silently rot the moment kb.py changed, and a
    budget tool that disagrees with the gate is actively harmful — it would
    approve drafts the gate rejects. So parse the constants from source and
    fail loudly (exit 3) if they can no longer be found.
    """
    kb_py = (kb_root or DEFAULT_KB_ROOT) / "tools" / "kb.py"
    if not kb_py.exists():
        return None, f"kb.py not found at {kb_py}"
    src = kb_py.read_text(encoding="utf-8")
    out = {}
    for name in ("CHUNK_HARD_LIMIT", "CURRENT_UNDERSTANDING_THRESHOLD"):
        m = re.search(rf"^{name}\s*=\s*(\d+)", src, re.MULTILINE)
        if not m:
            return None, f"could not read {name} from kb.py (tool is stale)"
        out[name] = int(m.group(1))
    return out, None


def stage_for(count: int) -> str:
    if count >= 8:
        return "evergreen"
    if count >= 3:
        return "budding"
    return "seedling"


def chunks(body: str):
    """Split into retrieval chunks the way kb.py does.

    CHUNK NOTE — kb.py's _chunk_errors treats EVERY H2 and H3 as owning the
    text that follows it up to the next H2/H3. That is the property that makes
    `###` sub-sectioning a genuine fix for an oversized entry rather than a
    cosmetic one, and it is why this tool must model H3 too: a checker that
    only split on H2 would over-report.
    """
    lines = body.splitlines(keepends=True)
    heads = []
    offset = 0
    for i, line in enumerate(lines):
        m = STRUCTURAL.match(line.rstrip("\n"))
        if m:
            heads.append((i, m.group(1), m.group(2)))
        offset += len(line)
    out = []
    for idx, (line_i, hashes, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        text = "".join(lines[line_i:end])
        out.append({"level": len(hashes), "title": title, "chars": len(text)})
    return out


def analyse(
    slug: str,
    entry: str | None,
    limits: dict,
    kb_root: pathlib.Path | None = None,
):
    path = (kb_root or DEFAULT_KB_ROOT) / "topics" / f"{slug}.md"
    if not path.exists():
        return None, f"topic not found: {path}"
    body = path.read_text(encoding="utf-8")

    before = len(DATED_H2.findall(body))
    new_dated = len(DATED_H2.findall(entry)) if entry else 0
    after = before + new_dated

    # Model the append the way capture does it: before "## Related" if present,
    # else at end of file. Either way the entry's own chunks are what matter.
    projected = body
    if entry:
        if "\n## Related\n" in body:
            projected = body.replace("\n## Related\n",
                                     "\n" + entry.rstrip("\n") + "\n\n## Related\n", 1)
        else:
            projected = body.rstrip("\n") + "\n\n" + entry.rstrip("\n") + "\n"

    hard = limits["CHUNK_HARD_LIMIT"]
    thresh = limits["CURRENT_UNDERSTANDING_THRESHOLD"]
    all_chunks = chunks(projected)
    over = [c for c in all_chunks if c["chars"] > hard]

    entry_chunks = chunks(entry) if entry else []
    entry_over = [c for c in entry_chunks if c["chars"] > hard]

    has_cu = any(c["level"] == 2 and c["title"] == "Current understanding"
                 for c in all_chunks)
    # A CU section may itself be soft-chunk-split into `###` children (garden
    # does this on big evergreen pages). Then the H2 owns only its heading
    # line, and reporting that tiny number as "headroom" would invite adding
    # kilobytes to a section whose real content sits in the children. Report
    # BOTH: the H2's own chunk, and the largest child chunk that is the real
    # constraint. (Verified 2026-07-28 against github-actions-discipline, whose
    # H2 measures 26c because of a `### Core thesis...` split.)
    cu = None
    cu_children = []
    for idx, c in enumerate(all_chunks):
        if c["level"] == 2 and c["title"] == "Current understanding":
            cu = c
            for nxt in all_chunks[idx + 1:]:
                if nxt["level"] == 2:
                    break
                cu_children.append(nxt)
            break

    report = {
        "slug": slug,
        "hard_limit": hard,
        "dated_entries_before": before,
        "dated_entries_after": after,
        "stage_before": stage_for(before),
        "stage_after": stage_for(after),
        "stage_changes": stage_for(before) != stage_for(after),
        "current_understanding_required": after >= thresh,
        "current_understanding_present": has_cu,
        "current_understanding_chars": cu["chars"] if cu else None,
        "current_understanding_subsections": cu_children,
        "entry_chunks": entry_chunks,
        "oversized_in_entry": entry_over,
        "oversized_anywhere": over,
    }
    return report, None


def emit(report: dict) -> int:
    hard = report["hard_limit"]
    fail = False
    print(f"topic: {report['slug']}  (hard chunk limit {hard:,}c)")
    print(f"dated entries: {report['dated_entries_before']} → "
          f"{report['dated_entries_after']}"
          + ("  [stage %s → %s — UPDATE frontmatter]"
             % (report["stage_before"], report["stage_after"])
             if report["stage_changes"] else ""))

    if report["entry_chunks"]:
        print("\ndrafted entry chunks:")
        for c in report["entry_chunks"]:
            flag = "  ✗ OVER" if c["chars"] > hard else ""
            print(f"  {'#' * c['level']} {c['title'][:64]}"
                  f"  {c['chars']:,}c{flag}")

    if report["oversized_in_entry"]:
        fail = True
        print(f"\nFAIL: {len(report['oversized_in_entry'])} chunk(s) in the draft "
              f"exceed {hard:,}c.")
        print("  Fix by SPLITTING, not trimming: insert an `###` sub-heading at a "
              "conceptual break (kb.py starts a new chunk at every H2 AND H3), or "
              "promote a distinct case-study to its own topic. Do this now — "
              "restructuring a draft is cheap, rewriting finished prose is not.")

    other = [c for c in report["oversized_anywhere"]
             if c not in report["oversized_in_entry"]]
    if other:
        fail = True
        print(f"\nFAIL: {len(other)} PRE-EXISTING oversized chunk(s) on this page "
              f"will also fail the gate:")
        for c in other:
            print(f"  {'#' * c['level']} {c['title'][:64]}  {c['chars']:,}c")

    if report["current_understanding_required"]:
        if not report["current_understanding_present"]:
            fail = True
            print(f"\nFAIL: this append reaches "
                  f"{report['dated_entries_after']} dated entries, so "
                  f"`## Current understanding` is REQUIRED as the first H2 "
                  f"(kb.py enforces it). Write it in the same pass — you have "
                  f"the page in context now.")
        else:
            cu = report["current_understanding_chars"] or 0
            kids = report.get("current_understanding_subsections") or []
            if kids:
                worst = max(kids, key=lambda c: c["chars"])
                print(f"\n`## Current understanding` present, soft-split into "
                      f"{len(kids)} `###` sub-section(s); the H2 itself holds "
                      f"{cu:,}c (heading only).")
                note = "  ✗ OVER" if worst["chars"] > hard else \
                    f"  ({hard - worst['chars']:,}c headroom)"
                print(f"  largest sub-section: ### {worst['title'][:56]}  "
                      f"{worst['chars']:,}c{note}")
                print("  Grow the RIGHT sub-section — the H2's own size is not "
                      "the constraint here.")
                if worst["chars"] > hard:
                    fail = True
                cu = 0  # H2 itself cannot be the failure in a split section
            else:
                room = hard - cu
                note = "  ✗ OVER" if cu > hard else f"  ({room:,}c headroom)"
                print(f"\n`## Current understanding` present: {cu:,}c{note}")
            print("  Remember to REGENERATE it and bump the "
                  "`<!-- current-understanding regenerated: -->` date — a stale "
                  "section outranks the newer entry it no longer reflects.")
            if cu > hard:
                fail = True

    if not fail:
        print("\nOK: no predicted kb.py check failures from this append.")
    return 1 if fail else 0


def self_check(limits: dict) -> int:
    """Confirm the tool is reading real limits and modelling H3 as a boundary."""
    sample = "## A (2026-01-01)\n" + ("x" * 50) + "\n### B\n" + ("y" * 50) + "\n"
    cs = chunks(sample)
    ok = len(cs) == 2 and cs[0]["level"] == 2 and cs[1]["level"] == 3
    print(f"limits read from kb.py: {limits}")
    print(f"H3 starts a new chunk: {'yes' if ok else 'NO — model is wrong'}")
    return 0 if ok else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--entry-file", help="file holding the drafted H2 entry")
    ap.add_argument(
        "--kb-root",
        help="knowledge-base checkout to inspect (overrides worktree detection)",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    kb_root = resolve_kb_root(explicit=args.kb_root)
    limits, err = read_limits(kb_root)
    if limits is None:
        print(f"{err}\nRefusing to guess: a budget that disagrees with the gate "
              f"would approve drafts the gate rejects.", file=sys.stderr)
        return 3

    if args.self_check:
        return self_check(limits)
    if not args.slug:
        ap.error("give a topic slug, or --self-check")

    entry = None
    if args.entry_file:
        p = pathlib.Path(args.entry_file)
        if not p.exists():
            print(f"entry file not found: {p}", file=sys.stderr)
            return 2
        entry = p.read_text(encoding="utf-8")

    report, err = analyse(args.slug, entry, limits, kb_root)
    if report is None:
        print(err, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if (report["oversized_anywhere"]
                     or (report["current_understanding_required"]
                         and not report["current_understanding_present"])) else 0
    return emit(report)


if __name__ == "__main__":
    sys.exit(main())
