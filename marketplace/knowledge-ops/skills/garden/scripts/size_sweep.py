#!/usr/bin/env python3
"""Measure size pressure across the four capped surfaces and classify the
STRUCTURAL remedy for each breach. Reports; never edits.

WHY A SEPARATE SCRIPT: `analyze.py` is pinned to knowledge-base topic semantics
(frontmatter contract, dated-entry stages, wiki-links, MoCs). Three of the four
surfaces here have none of those. Keeping them apart means `leaf_chunks`'s
deliberate byte-for-byte agreement with the KB CI gate is not put at risk by
edits made for `rules/` or `hooks/`.

THE CENTRAL RULE — SPLIT, NEVER TRIM. Every cap's own source prescribes
relocation, not deletion, and two say so in as many words:

  knowledge-base/.claude/rules/topic-authoring.md:36
    "Split dense material with concept-named `###` headings; do not trim
     load-bearing evidence."

  Anthropic skill best-practices (live, verified 2026-07-29)
    "Bundle comprehensive resources: Include complete API docs, extensive
     examples, large datasets; no context penalty until accessed"
    "Reference files, data, or documentation don't consume context tokens
     until actually read"

That second quote is the load-bearing one: content moved behind a pointer costs
ZERO until read, so splitting is strictly better than trimming — it preserves
the evidence AND removes the cost. Trimming only destroys. A sweep that trims to
satisfy a threshold is worse than no sweep.

WHAT THIS DELIBERATELY DOES NOT DO: measure aggregate ambient token load.
`/context-budget` already owns that, and it matters more than any per-file cap —
`rules/` totals ~624 KB (~155K tokens) loaded EVERY session, so bringing one 43 KB
file to 37 KB saves under 1% of it. This script finds files whose SHAPE is wrong;
it does not rank the architecture's total cost. Read both.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

HOME = Path.home()

# ── Caps, each with its provenance and the remedy its OWN source prescribes ──
#
# `hard` means a gate actually fails/blocks; `soft` means degradation only.
# A soft cap is a candidate for judgment, not an automatic edit.
SURFACES = {
    "rules": {
        "glob": str(HOME / ".claude" / "rules" / "*.md"),
        "unit": "bytes",
        "warn": 35_000,
        "cap": 38_000,          # rule-size-guard.py BLOCK_THRESHOLD
        "hard_ceiling": 40_000,  # observed Claude Code performance-warning floor
        "kind": "hard",
        "source": "hooks/rule-size-guard.py (WARN 35k / BLOCK 38k / HARD 40k)",
        "remedy": "extract older INCIDENT narratives to rules/incidents/<name> "
                  "leaving a one-line pointer; or move advisory reference "
                  "material to a knowledge-base topic",
        "auto": False,  # judgment: which incidents are still load-bearing?
        "why_not_auto": "choosing WHICH incident narratives may be demoted is "
                        "editorial — a still-firing GUARD's incident is load-"
                        "bearing, an archived one is not, and the script cannot "
                        "tell them apart",
    },
    "skills": {
        "glob": str(HOME / ".claude" / "skills" / "*" / "SKILL.md"),
        "unit": "lines",
        "warn": 460,
        "cap": 510,             # validate-skills.py C1 (500 soft + 10 tolerance)
        "hard_ceiling": None,   # Anthropic: explicitly exceedable with cause
        "kind": "soft",
        "source": "Anthropic best-practices 'under 500 lines (or has clear "
                  "reason to exceed)' + validate-skills.py C1 <=510",
        "remedy": "move detail into references/<topic>.md ONE level deep from "
                  "SKILL.md (zero context cost until read); SKILL.md becomes "
                  "the overview/table-of-contents",
        "auto": False,
        "why_not_auto": "Anthropic sanctions exceeding 500 lines with cause, so "
                        "a breach is not per se a defect; and which prose is "
                        "'detail' vs a load-bearing always-fire gate is a "
                        "judgment the line count cannot make",
    },
    "agent-memory": {
        "glob": str(HOME / ".claude" / "agent-memory" / "topics" / "*.md"),
        "unit": "bytes",
        "warn": 8_192,
        # 10,000-char vendor cap on hook output, minus ~450B for the
        # auto-topic-loader's label line + JSON envelope (measured across three
        # emission/stub pairs). NOT the 8,192 in ARCHITECTURE.md — that number
        # is a token-thrift guess that happens to sit just under the real cliff,
        # which is why files at 8,614B still deliver.
        "cap": 9_550,
        "hard_ceiling": 9_550,
        # HARD, not soft: over this the harness persists the payload and injects
        # a ~2KB preview, so 85-98% of the topic never enters context. That is a
        # delivery failure, not a cost inefficiency.
        "kind": "hard",
        "source": "code.claude.com/docs/en/hooks (verified 2026-07-29): 'Hook "
                  "output strings, including additionalContext, systemMessage, "
                  "and plain stdout, are capped at 10,000 characters. Output "
                  "that exceeds this limit is saved to a file and replaced with "
                  "a preview and file path.' Bracketed locally: firecrawl.md "
                  "(8,614B) inline; security.md (13,460B) persisted.",
        "remedy": "MULTI-WAY decompose into as many <topic>-<subdomain>.md "
                  "siblings as the size requires (8-15, not one), plus a hub "
                  "pointer block in the core file; descend to ### granularity "
                  "for any ## section that is over cap on its own",
        # MEASURED TWICE, and the first measurement was WRONG — recorded because
        # the error is instructive.
        #
        # Attempt 1 asked "does ONE split reach the cap?" A six-way split of
        # claude-monitoring.md left 5 of 6 siblings over, so this was set
        # `auto: False` with "unsplittable at ## granularity" for github.md and
        # claude-code-config.md. Both conclusions were artifacts of the question:
        # a single split was never going to fit 119 KB into 8 KB bins, and
        # measuring only `##` hid the `###` seams inside the big sections.
        #
        # Attempt 2 packed whole units into AS MANY bins as needed, descending to
        # ### for any over-cap section (first-fit-decreasing):
        #   claude-monitoring   118,410B  56 units -> 15 siblings, 0 over cap
        #   github               86,605B  56 units -> 11 siblings, 0 over cap
        #   kaggle               64,954B  29 units ->  9 siblings, 0 over cap
        #   claude-code-config   59,930B  50 units ->  8 siblings, 0 over cap
        #   msgraph              57,144B  44 units ->  8 siblings, 0 over cap
        #   platform-changelog   45,503B  15 units ->  6 siblings, 1 over cap
        # github and claude-code-config — the two called "unsplittable" — are
        # FEASIBLE once you look at ###. 5 of 6 land every sibling under cap.
        #
        # The single genuine blocker across all six is ONE 11,750B `###`-less
        # section in platform-changelog.md ("Claude Code Session Behavior").
        # That is one exception, not a class.
        #
        # Still `auto: False`, but for a DIFFERENT and narrower reason: the
        # packing proves FEASIBILITY, not the taxonomy. Bin-packing by size
        # produces siblings grouped by nothing a reader would recognize, and a
        # topic file's value is that its name predicts its contents. Naming 15
        # coherent subdomains is authorial.
        "auto": False,
        "why_not_auto": "feasibility is PROVEN (multi-way packing lands every "
                        "sibling under cap on 5 of 6 worst files, incl. the two "
                        "previously miscalled unsplittable) — but size-based "
                        "packing yields siblings grouped by nothing a reader "
                        "recognizes. The blocker is the subdomain TAXONOMY, not "
                        "the split: a topic's name must predict its contents. "
                        "Plan one with scripts/split_plan.py <file> — it reports the sibling count and per-sibling feasibility, and names the taxonomy decision a human owns",
    },
    "kb-topics": {
        "glob": str(HOME / "Documents" / "knowledge-base" / "topics" / "*.md"),
        "unit": "bytes",
        "warn": 7_000,
        "cap": 8_192,
        "hard_ceiling": None,
        "kind": "soft",
        "source": "ARCHITECTURE.md Layer-2 soft cap; garden Step 3 item 3",
        "remedy": "hub-split (backlog) — the file-level cap is advisory here "
                  "because retrieval is CHUNK-level; see kb-chunks",
        "auto": False,
        "why_not_auto": "KB retrieval is chunk-level, so file size is a weak "
                        "signal; hub-splitting is already backlogged by "
                        "analyze.py's hub_split_candidates",
    },
}

# The KB's only HARD size gate: `kb.py check` fails a chunk over this.
KB_CHUNK_HARD = 3_000
KB_CHUNK_SOFT = 2_500
# `_moc-*` dashboards are generated navigation surfaces; their "Recently Added"
# sections legitimately exceed the chunk cap and analyze.py already skips them.
KB_CHUNK_SKIP_PREFIXES = ("dashboard-", "_moc-")

# Rolling logs rewritten wholesale by automation. Splitting one fights its
# producer — the next run rewrites the file and the siblings orphan instantly.
HOOK_MANAGED = {"session-friction-patterns.md"}

# agent-memory files that are DELIBERATE archives: they exist because a parent
# topic was already split, and re-flagging them as new findings is noise.
# (garden SKILL.md Step 3 item 3 names these two explicitly.)
KNOWN_ARCHIVE_EXCEPTIONS = {"aws-infra-misc.md", "aws-infra-s3.md"}


def leaf_chunks(content: str) -> list[tuple[str, int]]:
    """Chunk measurement pinned to the KB CI gate. Copied deliberately, not
    imported: analyze.py's docstring warns the +3/+4 offsets and whole-content
    split are load-bearing for agreement with the gate, so this must not drift
    via a shared-helper refactor. Any change here must change BOTH.
    """
    out: list[tuple[str, int]] = []
    for sec in re.split(r"(?m)^##\s", content)[1:]:
        parts = re.split(r"(?m)^###\s", sec)
        h2h = "## " + sec.split("\n")[0]
        if len(parts) == 1:
            out.append((h2h[:70], 3 + len(sec)))
        else:
            out.append((h2h[:70] + " [pre-###]", 3 + len(parts[0])))
            for sub in parts[1:]:
                out.append(("### " + sub.split("\n")[0][:66], 4 + len(sub)))
    return out


def _measure(path: str, unit: str) -> int:
    if unit == "lines":
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    return os.path.getsize(path)


def _loader_routed_topics() -> set[str]:
    """Topics the auto-topic-loader can INJECT (and so are capped at 10,000).

    This is the discriminator that turns 21 size findings into ~4 real ones. A
    topic reached only by an explicit `Read` never hits the hook-output cap —
    `Read` has a far higher limit — so its size is a token-cost question, not a
    delivery failure. Only a topic in the loader's route map can be silently
    truncated to a ~2KB preview mid-task.

    Reads the loader's own map rather than duplicating it, so this cannot drift.

    Returns None (NOT an empty set) when the map cannot be read. The distinction
    is load-bearing: an empty set is the positive claim "no topic is routed", and
    a caller that stamps every file "no delivery penalty" on that basis has
    reported UNKNOWN as PASS. A verifier must distinguish three states — routed /
    not-routed / could-not-determine — because an unreadable route map and a
    genuinely empty one produce identical output from a two-state verifier.
    (Caught 2026-07-29 by probing this function's own failure path: with the
    loader unreadable, the sweep cleared all 21 over-cap files as safe.)
    """
    import importlib.util
    try:
        hooks = HOME / ".claude" / "hooks"
        spec = importlib.util.spec_from_file_location(
            "_atl_probe", hooks / "auto-topic-loader.py")
        if spec is None or spec.loader is None:
            return None  # cannot load = UNKNOWN, not "nothing routed"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return set(mod._build_server_to_topic_map().values())
    except Exception:
        return None


def _has_references_dir(skill_md: str) -> bool:
    """A skill already using progressive disclosure is a different case from one
    that has never split — the remedy is 'move MORE detail out', not 'start'."""
    return Path(skill_md).parent.joinpath("references").is_dir()


def sweep_surface(name: str, spec: dict) -> dict:
    files = sorted(glob.glob(spec["glob"]))
    # None = route map unreadable (UNKNOWN), set() = readable and empty.
    routed = _loader_routed_topics() if name == "agent-memory" else set()
    over, near, ok = [], [], 0
    for f in files:
        base = os.path.basename(f)
        n = _measure(f, spec["unit"])
        ratio = n / spec["cap"]
        row = {
            "file": base if name != "skills" else Path(f).parent.name,
            "path": f,
            "size": n,
            "unit": spec["unit"],
            "cap": spec["cap"],
            "pct_of_cap": round(ratio * 100),
            "over_by": max(0, n - spec["cap"]),
        }
        if name == "skills":
            row["has_references"] = _has_references_dir(f)
        if name == "agent-memory":
            # THE discriminator: only a loader-ROUTED topic can be silently
            # truncated mid-task. An unrouted one is read explicitly (no cap),
            # so being over 9,550B costs tokens, not correctness.
            if routed is None:
                # UNKNOWN, never PASS. Claiming "no delivery penalty" here would
                # be a positive safety claim derived from a failed read.
                row["loader_routed"] = None
                row["severity_reason"] = (
                    "UNKNOWN — could not read the auto-topic-loader route map, so "
                    "whether this topic is injected (and therefore truncated) is "
                    "undetermined. Treat as possibly-INJECTED until the map reads."
                )
            else:
                row["loader_routed"] = base in routed
                row["severity_reason"] = (
                    "INJECTED — content silently absent mid-task"
                    if base in routed else
                    "read-only — over budget but no delivery penalty"
                )
        if base in HOOK_MANAGED:
            row["exempt"] = "hook-managed rolling log (splitting fights its producer)"
            ok += 1
            continue
        if base in KNOWN_ARCHIVE_EXCEPTIONS:
            row["exempt"] = "deliberate archive sibling from a prior split"
            ok += 1
            continue
        if spec["hard_ceiling"] and n > spec["hard_ceiling"]:
            row["severity"] = "BREACH-CEILING"
        elif n > spec["cap"]:
            row["severity"] = "OVER-CAP"
        if n > spec["cap"]:
            over.append(row)
        elif n > spec["warn"]:
            row["severity"] = "NEAR"
            near.append(row)
        else:
            ok += 1

    # Sort by SEVERITY first, size second. Sorting by size alone lets files with
    # NO delivery defect outrank the ones that are actually truncated, and since
    # the human report prints only the top 6, a real finding can be pushed below
    # the "… N more" line by a bigger file that costs nothing until read.
    # Measured 2026-07-29: claude-monitoring.md (119 KB, read-only, harmless) led
    # the list while 3 of the 4 genuinely-truncated topics were hidden.
    # Rank: UNKNOWN (undetermined) > INJECTED (truncated) > read-only/other.
    def _severity_rank(r):
        routed = r.get("loader_routed", "n/a")
        if routed is None:
            return 0
        if routed is True:
            return 1
        return 2

    over.sort(key=lambda r: (_severity_rank(r), -r["size"]))
    near.sort(key=lambda r: (_severity_rank(r), -r["size"]))
    return {
        "surface": name,
        "kind": spec["kind"],
        "cap": spec["cap"],
        "unit": spec["unit"],
        "hard_ceiling": spec["hard_ceiling"],
        "source": spec["source"],
        "remedy": spec["remedy"],
        "auto_resolvable": spec["auto"],
        "why_not_auto": spec["why_not_auto"],
        "counts": {"total": len(files), "over": len(over), "near": len(near), "ok": ok},
        "over": over,
        "near": near,
    }


def sweep_kb_chunks() -> dict:
    """The ONLY hard-failing size gate in the KB. Chunk-level, not file-level."""
    hard, soft, total = [], [], 0
    for f in sorted(glob.glob(str(HOME / "Documents" / "knowledge-base" / "topics" / "*.md"))):
        base = os.path.basename(f)
        if base.startswith(KB_CHUNK_SKIP_PREFIXES):
            continue
        content = Path(f).read_text(encoding="utf-8", errors="replace")
        for hdr, clen in leaf_chunks(content):
            total += 1
            if clen > KB_CHUNK_HARD:
                hard.append({"file": base, "header": hdr, "chars": clen})
            elif clen > KB_CHUNK_SOFT:
                soft.append({"file": base, "header": hdr, "chars": clen})
    hard.sort(key=lambda r: -r["chars"])
    soft.sort(key=lambda r: -r["chars"])
    return {
        "surface": "kb-chunks",
        "kind": "hard",
        "cap": KB_CHUNK_HARD,
        "unit": "chars",
        "hard_ceiling": KB_CHUNK_HARD,
        "source": "knowledge-base/.claude/rules/topic-authoring.md:36 + kb.py check",
        "remedy": "split with concept-named ### headings — the source says "
                  "verbatim 'do not trim load-bearing evidence'",
        "auto_resolvable": True,
        "why_not_auto": None,
        "counts": {"total": total, "over": len(hard), "near": len(soft),
                   "ok": total - len(hard) - len(soft)},
        "over": hard,
        "near": soft,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--surface", help="limit to one surface")
    args = ap.parse_args()

    results = []
    for name, spec in SURFACES.items():
        if args.surface and args.surface != name:
            continue
        results.append(sweep_surface(name, spec))
    if not args.surface or args.surface == "kb-chunks":
        results.append(sweep_kb_chunks())

    if args.json:
        print(json.dumps({"surfaces": results}, indent=2))
        return 0

    print("SIZE SWEEP — structural remedies only; NEVER trim load-bearing content\n")
    for r in results:
        c = r["counts"]
        gate = "HARD (a gate fails)" if r["kind"] == "hard" else "SOFT (degrades only)"
        print(f"── {r['surface']}  [{gate}]  cap={r['cap']:,} {r['unit']}")
        print(f"   {c['over']} over · {c['near']} near · {c['ok']} ok  (of {c['total']})")
        print(f"   source: {r['source']}")
        print(f"   remedy: {r['remedy']}")
        print(f"   auto-resolvable: {r['auto_resolvable']}"
              + (f" — {r['why_not_auto']}" if r["why_not_auto"] else ""))
        for row in r["over"][:6]:
            sev = row.get("severity", "OVER-CAP")
            label = row.get("header", row["file"])
            extra = ""
            if "has_references" in row:
                extra = "  refs/ present" if row["has_references"] else "  NO refs/ yet"
            # Delivery status must be VISIBLE in the human report, not just the
            # JSON — the discriminator between "silently truncated mid-task" and
            # "merely large" is the whole point of this surface, and UNKNOWN must
            # never look like the benign case.
            if "loader_routed" in row:
                extra = {True: "  INJECTED (truncated)",
                         False: "  read-only",
                         None: "  DELIVERY UNKNOWN"}[row["loader_routed"]]
            print(f"     {sev:<15} {row.get('chars', row.get('size')):>8,} "
                  f"({row['pct_of_cap']:>3}%)  {label}{extra}")
        if len(r["over"]) > 6:
            print(f"     … {len(r['over']) - 6} more")
        print()

    unknown = [row for r in results for row in r["over"]
               if row.get("loader_routed", "n/a") is None]
    if unknown:
        print(f"!! DELIVERY UNDETERMINED for {len(unknown)} agent-memory topic(s): the "
              f"auto-topic-loader\n   route map could not be read, so injection status is "
              f"UNKNOWN -- not 'safe'.\n   Fix the loader import before trusting this "
              f"surface's severities.\n")

    total_over = sum(r["counts"]["over"] for r in results)
    print(f"TOTAL over cap: {total_over}")
    print("\nNOTE: aggregate ambient load is NOT measured here — /context-budget "
          "owns it,\nand it dominates: rules/ is ~624 KB (~155K tokens) loaded "
          "every session, so\nper-file descoping moves <1% of the real cost. "
          "This sweep finds wrong SHAPE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
