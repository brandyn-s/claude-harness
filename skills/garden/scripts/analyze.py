#!/usr/bin/env python3
"""
garden/analyze.py — deterministic mechanical analysis for the /garden skill.

Performs the NON-judgment parts of a garden health check and emits a single
JSON report to a temp path (NOT into the staging repo, so it can never trip
the push). The /garden skill (LLM) consumes the JSON and applies the judgment
parts: orphan/MoC-gap fit-ladder placement, HIGH-confidence merges, and
concept-named soft-chunk splitting.

Why this exists: three components measure the same things and MUST agree, or
garden churns —
  * dated-entry regex is shared with /capture (capture/SKILL.md:209)
  * leaf-chunk algorithm is shared with the KB CI gate (.github/workflows/ci.yml)
Computing either differently reintroduces the absorb stage flip-flop / phantom
chunk-count class of bug. Keep these two algorithms byte-aligned with their
upstreams; if the CI gate changes its chunking, change leaf_chunks() to match.

Usage:
    python3 analyze.py [TOPICS_DIR]
    (TOPICS_DIR defaults to ~/Documents/knowledge-base/topics)

Output: prints the JSON report path on stdout (last line). Read that file.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ── Shared algorithms (keep aligned with upstreams) ──────────────────────────

# Dated-entry regex — shared with /capture (capture/SKILL.md:209).
DATED_ENTRY_RE = re.compile(r"^## .* \(\d{4}-\d{2}-\d{2}\)", re.MULTILINE)

# Non-canonical date-FIRST entry headers ("## 2026-06-07: Title",
# "## 2026-06-07 — Title"). Invisible to DATED_ENTRY_RE, so they corrupt the
# stage count AND the suspect-MoC classification (a topic whose every entry is
# date-first reads as dated==0). 67 of these were normalized corpus-wide on
# 2026-06-10; this detection keeps the class from re-accumulating.
NONCANONICAL_DATED_RE = re.compile(
    r"^## (\d{4}-\d{2}-\d{2})\s*[:—–-]?\s+(.+)$", re.MULTILINE)
TRAILING_DATE_RE = re.compile(r"\(\d{4}-\d{2}-\d{2}\)")
ENTRY_MARKER_RE = re.compile(r"\s*(\[(?:verified|observed|confirmed)\])\s*$")

# Open state-claim markers (KB CLAUDE.md "Status markers for state-claims").
OPEN_MARKER_RE = re.compile(r"^> \*\*STATUS:\*\* OPEN\b(.*)$", re.MULTILINE)
# No closing-paren anchor: annotated forms like "(since 2026-06-09; narrowed
# 2026-06-09)" are dated markers, not violations.
SINCE_RE = re.compile(r"\(since (\d{4}-\d{2}-\d{2})")

# Hub-split thresholds (KB CLAUDE.md "Garden maintenance"): a topic this large
# buries its own concepts at the topic level even when every chunk is compliant.
HUB_SPLIT_SECTIONS = 30
HUB_SPLIT_BYTES = 80_000

# No rolling knowledge-base log currently has an active lifecycle producer.
# Keep this explicit set so a future bounded producer must opt its output into
# the exemption rather than inheriting a stale historical assumption.
HOOK_MANAGED = set()

# Current-understanding synthesis sections (KB CLAUDE.md "Current
# understanding (evergreen topics)"): required on topics with 8+ dated
# entries; regenerated in place by /capture; staleness is deterministic via
# the trailing regenerated: comment.
CU_HEADER_RE = re.compile(r"^## Current understanding\s*$", re.MULTILINE)
CU_REGEN_RE = re.compile(r"<!-- current-understanding regenerated: (\d{4}-\d{2}-\d{2}) -->")
CU_MIN_DATED_ENTRIES = 8

# Named non-promotion stages — garden never auto-promotes/demotes these.
NAMED_NON_PROMO = {"retired", "archived", "deprecated", "draft"}

# Files the CI gate (and therefore the chunk check) skips by filename prefix.
CHUNK_SKIP_PREFIXES = ("dashboard-", "_moc-")

# Garden's OWN backlog artifacts — they live in topics/ but are not knowledge
# topics, so they're excluded from stage / orphan / MoC-gap audits (they would
# otherwise be perpetually flagged). They ARE still inventoried and chunk-checked.
# canonicalization-candidates.md in particular uses dated `## Identifier: X
# (YYYY-MM-DD)` headers that collide with the dated-entry regex, which would
# otherwise climb its stage monotonically as the backlog grows.
BACKLOG_FILES = {"canonicalization-candidates.md", "harness-pruning-candidates.md",
                 "hub-split-candidates.md"}


def leaf_chunks(content):
    """Replicate the KB CI gate's leaf-chunk measurement EXACTLY
    (.github/workflows/ci.yml). Returns list of (header_preview, char_len).

    The gate splits the whole file on '^##\\s', skips the pre-first-## part,
    then within each ## section splits on '^###\\s'. Chunk length INCLUDES the
    header marker: 3 for '## ', 4 for '### '. Do not "simplify" this — the +3/+4
    and the whole-content split are load-bearing for agreement with the gate.
    """
    out = []
    sections = re.split(r"(?m)^##\s", content)
    for sec in sections[1:]:
        parts = re.split(r"(?m)^###\s", sec)
        if len(parts) == 1:
            clen = 3 + len(sec)
            h2h = "## " + sec.split("\n")[0]
            out.append((h2h[:70], clen))
        else:
            pre_len = 3 + len(parts[0])
            h2h = "## " + sec.split("\n")[0]
            out.append((h2h[:70] + " [pre-###]", pre_len))
            for sub in parts[1:]:
                clen = 4 + len(sub)
                h3h = "### " + sub.split("\n")[0]
                out.append((h3h[:70], clen))
    return out


# ── Frontmatter + link parsing ───────────────────────────────────────────────

def parse_frontmatter(content):
    fm = {}
    if not content.startswith("---"):
        return fm
    end = content.find("\n---", 3)
    if end == -1:
        return fm
    for line in content[3:end].splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if k in ("title", "stage", "stage_pinned", "description", "created",
                 "updated", "cssclasses"):
            fm[k] = v.strip('"').strip("'")
        elif k == "tags":
            fm["tags"] = re.findall(r"[\w-]+", v)
    return fm


def mask_for_links(content):
    """Mask fenced code blocks (block level) then inline backtick spans
    (per line) so wiki-link extraction never matches documentation examples."""
    return re.sub(r"```[\s\S]*?```", lambda m: " " * len(m.group(0)), content)


def extract_wiki_links(content):
    """Return [{slug, display, raw}] for real (non-documentation) wiki-links.
    Strips #anchor suffix; same-page [[#anchor]] yields empty slug (caller skips).
    Unescapes the markdown-table pipe: inside a table cell the separator MUST be
    written `\\|`, so splitting on a raw `|` leaves a trailing backslash on the
    slug and every such link reads as broken. Garden's auto-resolution for a
    broken link is to strip the `[[]]` wrapping, so this would DESTROY valid
    links (2026-08-01: m365-audit-data-reachability.md:60)."""
    masked = mask_for_links(content)
    links = []
    for line in masked.splitlines():
        line = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), line)
        for m in re.finditer(r"\[\[([^\]]+)\]\]", line):
            inner = m.group(1).replace("\\|", "|")
            slug_part, display = (inner.split("|", 1) + [None])[:2] if "|" in inner else (inner, None)
            slug = slug_part.split("#", 1)[0] if "#" in slug_part else slug_part
            links.append({"slug": slug.strip(), "display": display, "raw": m.group(0)})
    return links


# ── Main analysis ─────────────────────────────────────────────────────────────

def link_list_ratio(content):
    """Fraction of non-empty body lines that are list items carrying a wiki-link.
    Real MoCs are mostly '- [[slug|Title]] -- descriptor' lines; reference-style
    topics (absorb profiles, landscape reports) are mostly prose."""
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4:]
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    linky = sum(1 for ln in lines
                if re.match(r"\s*[-*] ", ln) and "[[" in ln)
    return linky / len(lines)


def classify(fname, dated, sections, css, content=""):
    if fname.startswith("_moc-") or fname.endswith("-moc.md") or fname == "index.md":
        return "moc"
    if fname.startswith("dashboard-"):
        return "dashboard"
    if "moc" in css or "index" in css:
        return "moc"
    # suspect_moc needs MoC-like SHAPE, not just zero dated entries — the
    # 2026-06-08 run classified all 22 zero-dated absorb-* reference topics as
    # suspect MoCs, silently dropping them from the orphan AND MoC-gap checks
    # (root cause of the 27-orphan accumulation found 2026-06-10). A file that
    # is mostly prose is a topic regardless of its dated-entry count.
    if dated == 0 and sections >= 3 and link_list_ratio(content) >= 0.5:
        return "suspect_moc"
    return "topic"


def stage_for_count(n):
    if n <= 2:
        return "seedling"
    if n <= 7:
        return "budding"
    return "evergreen"


def analyze(topics_dir):
    topics = Path(topics_dir)
    files = sorted(topics.glob("*.md"))
    existing_slugs = {f.stem for f in files}

    data = {}
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError, IsADirectoryError) as e:
            sys.stderr.write(f"WARNING: Skipping {f.name}: {e}\n")
            continue
        fm = parse_frontmatter(content)
        dated = len(DATED_ENTRY_RE.findall(content))
        sections = len(re.findall(r"^## ", content, re.MULTILINE))
        data[f.name] = {
            "fm": fm,
            "dated": dated,
            "sections": sections,
            "links": extract_wiki_links(content),
            "content": content,
        }

    cls = {fn: classify(fn, d["dated"], d["sections"], d["fm"].get("cssclasses", ""),
                        d["content"])
           for fn, d in data.items()}

    # Tracker/backlog exemption — hardcoded names plus anything tagged
    # `maintenance` (KB CLAUDE.md: auto-generated working lists whose dated
    # headers are list items, not capture events; they stay seedling).
    exempt = set(BACKLOG_FILES) | {
        fn for fn, d in data.items()
        if "maintenance" in d["fm"].get("tags", [])}

    # Stage audit (topics only; skip named non-promotion stages).
    # Under-promotion (count crossed a threshold, stage lags) is auto-fixable;
    # over-staging (stage above what the dated count supports — reference-style
    # topics, hub pages after a split, deliberate curator choices) is
    # REPORT-ONLY: garden's demotion rule only fires after merges/manual entry
    # removal, never from a band recount (see SKILL.md "Demotion").
    stage_order = {"seedling": 0, "budding": 1, "evergreen": 2}
    stage_counts = {"seedling": 0, "budding": 0, "evergreen": 0, "named_other": 0}
    stage_mismatches, stage_overstaged = [], []
    for fn, d in data.items():
        if cls[fn] != "topic" or fn in exempt:
            continue
        cur = d["fm"].get("stage", "").lower()
        if cur in NAMED_NON_PROMO:
            stage_counts["named_other"] += 1
            continue
        # Curator pin: `stage_pinned: true` marks the stage as a deliberate
        # choice — exempt from the whole audit (no promotion, no overstaged
        # row). Without it, report-only overstaged rows for curator-chosen
        # staging re-appear every run as permanent noise (5 of 7 on 2026-08-22).
        # Strip an inline YAML comment first: the naive frontmatter parser
        # keeps it, so `stage_pinned: true  # garden: ...` reads as non-true
        # (measured 2026-08-22 — the pin silently failed on the live corpus).
        pinned = d["fm"].get("stage_pinned", "").split("#", 1)[0].strip().lower()
        if pinned in ("true", "yes"):
            continue
        should = stage_for_count(d["dated"])
        stage_counts[should] += 1
        row = {"file": fn, "current": cur or "(missing)",
               "should_be": should, "entry_count": d["dated"]}
        if cur not in stage_order:
            stage_mismatches.append(row)        # missing → initial assignment
        elif stage_order[cur] < stage_order[should]:
            stage_mismatches.append(row)        # under-promoted → auto-promote
        elif stage_order[cur] > stage_order[should]:
            # Hubs (topics with a `## Sub-topics` wiki-link index) are
            # STRUCTURALLY exempt from stage promotion — KB CLAUDE.md
            # "Hubs ... are EXEMPT — their body or overview already serves
            # the role." Their content lives in sub-topics, so a hub carries
            # 0 dated entries and only 1-2 `## ` sections (the index), which
            # the reference-SHAPE exemption below (needs >= 3 sections) does
            # NOT catch — so 9 of 14 overstaged were permanent unresolvable
            # noise every run (2026-07-24). Same `## Sub-topics` signal the
            # Current-understanding-coverage check uses.
            if "## Sub-topics" in d["content"]:
                continue
            # Zero-dated reference/profile topics (absorb profiles, landscape
            # reports) legitimately carry a curated stage despite 0 dated
            # entries; overstaged is report-only, so flagging them is pure
            # recurring noise (26 such every run, 2026-06-16 — dominated by
            # absorb-*). Exempt the reference SHAPE (no dated entries but real
            # structure); a near-empty mis-staged placeholder (sections < 3)
            # still surfaces.
            if d["dated"] == 0 and d["sections"] >= 3:
                continue
            stage_overstaged.append(row)        # report-only

    # Links: broken + bare (topics + suspect_mocs; skip moc/dashboard)
    broken_links, bare_links = [], []
    for fn, d in data.items():
        if cls[fn] in ("dashboard", "moc"):
            continue
        for link in d["links"]:
            slug = link["slug"]
            if not slug:
                continue
            if slug not in existing_slugs:
                broken_links.append({"file": fn, "link": link["raw"], "slug": slug,
                                     "display": link["display"]})
            elif link["display"] is None and "#" not in link["raw"]:
                bare_links.append({"file": fn, "link": link["raw"], "slug": slug,
                                   "target_title": data.get(slug + ".md", {}).get("fm", {}).get("title")})

    # Incoming-link index (strip anchors handled in extract; skip self-refs)
    incoming = {fn: [] for fn in data}
    for fn, d in data.items():
        for link in d["links"]:
            tgt = link["slug"] + ".md"
            if link["slug"] and tgt in incoming and tgt != fn:
                incoming[tgt].append(fn)

    orphan_topics = sorted(fn for fn, src in incoming.items()
                           if not src and cls.get(fn) == "topic" and fn not in exempt)

    moc_files = [fn for fn, c in cls.items() if c == "moc"]
    moc_listed = set()
    for mf in moc_files:
        for link in data[mf]["links"]:
            if link["slug"]:
                moc_listed.add(link["slug"] + ".md")
    moc_gap_topics = sorted(fn for fn, c in cls.items()
                            if c == "topic" and fn not in moc_listed and fn not in exempt)

    # Chunk violations — leaf-chunk algorithm shared with CI gate; skip dashboard-/_moc-
    hard_chunks, soft_chunks = [], []
    for fn, d in data.items():
        if any(fn.startswith(p) for p in CHUNK_SKIP_PREFIXES):
            continue
        for hdr, clen in leaf_chunks(d["content"]):
            if clen > 3000:
                hard_chunks.append({"file": fn, "header": hdr, "chars": clen})
            elif clen >= 2500:
                soft_chunks.append({"file": fn, "header": hdr, "chars": clen})

    # Non-canonical date-first headers → deterministic rewrite suggestion
    noncanonical = []
    for fn, d in data.items():
        if cls[fn] == "dashboard":
            continue
        for m in NONCANONICAL_DATED_RE.finditer(d["content"]):
            date, rest = m.group(1), m.group(2).strip()
            mk = ENTRY_MARKER_RE.search(rest)
            marker = ""
            if mk:
                marker = " " + mk.group(1)
                rest = rest[:mk.start()].rstrip()
            if TRAILING_DATE_RE.search(rest):
                suggested = f"## {rest}{marker}"
            else:
                suggested = f"## {rest} ({date}){marker}"
            noncanonical.append({"file": fn, "header": m.group(0)[:90],
                                 "suggested": suggested[:90]})

    # Stale `updated:` — older than the newest dated entry in the file
    stale_updated = []
    for fn, d in data.items():
        if cls[fn] == "dashboard":
            continue
        dates = re.findall(r"^## .* \((\d{4}-\d{2}-\d{2})\)", d["content"], re.MULTILINE)
        upd = d["fm"].get("updated", "")
        if dates and re.match(r"\d{4}-\d{2}-\d{2}$", upd) and max(dates) > upd:
            stale_updated.append({"file": fn, "updated": upd, "newest_entry": max(dates)})

    # Open-marker inventory + undated markers (suggested since-date is the
    # enclosing dated entry's date, else frontmatter created:). Each dated
    # marker carries age_days + age_band so the garden report can surface the
    # OLDEST gaps — a marker open >90d is unlikely to self-resolve and should
    # float up. NOTE: garden does NOT verify these against world-state or flip
    # cross-page-resolved ones; that reconciliation needs network/MCP/gh and
    # risks false RESOLVED flips, so it is out of scope (see SKILL.md
    # "Open-Status Markers"). This is inventory + aging only.
    today = datetime.date.today()
    open_markers, undated_markers = [], []
    for fn, d in data.items():
        if cls[fn] == "dashboard":
            continue
        cur_date = None
        for line in d["content"].splitlines():
            hm = re.match(r"^## .* \((\d{4}-\d{2}-\d{2})\)", line)
            if hm:
                cur_date = hm.group(1)
            elif line.startswith("## "):
                cur_date = None
            om = OPEN_MARKER_RE.match(line)
            if not om:
                continue
            since = SINCE_RE.search(om.group(1))
            if since:
                try:
                    age_days = (today - datetime.date.fromisoformat(since.group(1))).days
                except ValueError:
                    age_days = None
                band = ("over-90d" if age_days is not None and age_days > 90
                        else "30-90d" if age_days is not None and age_days >= 30
                        else "under-30d")
                open_markers.append({"file": fn, "since": since.group(1),
                                     "age_days": age_days, "age_band": band,
                                     "text": om.group(1).strip()[:120]})
            else:
                undated_markers.append({
                    "file": fn, "line": line[:120],
                    "suggested_since": cur_date or d["fm"].get("created") or ""})
    open_markers.sort(key=lambda m: m["since"])
    # Row list, not a count — every sibling field is rows, and the count-only
    # int crashed the first consumer that iterated it (2026-08-22). Oldest
    # first, inherited from the sort above.
    open_markers_over_90d = [m for m in open_markers if m["age_band"] == "over-90d"]

    # Current-understanding coverage + staleness (8+ dated entries; hubs,
    # trackers, hook-managed logs, and retired/archived topics exempt — a
    # retired topic's state IS "retired", no synthesis to maintain)
    cu_missing, cu_stale = [], []
    topic_newest_entries = {}
    for fn, d in data.items():
        if (cls[fn] != "topic" or fn in exempt or fn in HOOK_MANAGED
                or "## Sub-topics" in d["content"]
                or d["fm"].get("stage", "").lower() in NAMED_NON_PROMO):
            continue
        dates = re.findall(r"^## .* \((\d{4}-\d{2}-\d{2})\)", d["content"], re.MULTILINE)
        if dates:
            topic_newest_entries[fn] = max(dates)
        if d["dated"] < CU_MIN_DATED_ENTRIES:
            continue
        if not CU_HEADER_RE.search(d["content"]):
            cu_missing.append({"file": fn, "dated_entries": d["dated"]})
            continue
        regen = CU_REGEN_RE.search(d["content"])
        newest = max(re.findall(r"^## .* \((\d{4}-\d{2}-\d{2})\)", d["content"],
                                re.MULTILINE) or [""])
        if not regen:
            cu_stale.append({"file": fn, "regenerated": "(missing comment)",
                             "newest_entry": newest})
        elif newest and regen.group(1) < newest:
            cu_stale.append({"file": fn, "regenerated": regen.group(1),
                             "newest_entry": newest})

    # Hub-split candidates — too many parent chunks even if each is compliant
    hub_split = sorted(
        ({"file": fn, "sections": d["sections"], "bytes": len(d["content"])}
         for fn, d in data.items()
         if cls[fn] == "topic" and fn not in HOOK_MANAGED
         and (d["sections"] > HUB_SPLIT_SECTIONS or len(d["content"]) > HUB_SPLIT_BYTES)),
        key=lambda r: -r["bytes"])

    # Missing required frontmatter (CI gate also checks; report for parity) — skip moc/dashboard
    missing_fm = []
    for fn, d in data.items():
        if cls[fn] in ("dashboard", "moc"):
            continue
        for field in ("title", "description", "stage", "updated"):
            if not d["fm"].get(field):
                missing_fm.append({"file": fn, "field": field})

    # Placement data for the LLM's fit-ladder
    moc_tags = {mf: data[mf]["fm"].get("tags", []) for mf in moc_files}
    topic_tags = {fn: data[fn]["fm"].get("tags", []) for fn, c in cls.items() if c == "topic"}
    topic_titles = {fn: data[fn]["fm"].get("title", fn[:-3].replace("-", " ").title())
                    for fn, c in cls.items() if c == "topic"}

    # Merge-candidate pre-filter — PRECISE: a slug-prefix relationship
    # (litellm-llm-gateway ⊂ litellm-llm-gateway-next-steps) OR >=3 distinctive
    # shared title words. The SKILL runs memory_search ONLY on these pairs, NOT
    # per-topic: per-topic was ~250 calls at up to 76s cold each (observed
    # 2026-06-16). A loose tag/title-overlap bar produced 789 pairs — worse
    # than 250 — because related topics share tags BY DESIGN (absorb-*,
    # aws-deployment-*, terraform-ci-* are deliberate splits, not dupes). The
    # precise bar yields ~15 and surfaces the real prefix-pair candidates.
    # Merges are rare and the next run re-checks, so a tight (false-negative-
    # tolerant) filter is correct. Common topic-suffix words are stopped so
    # titles don't match on "api"/"patterns"/etc.
    TITLE_STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on",
                  "with", "vs", "api", "patterns", "architecture", "landscape",
                  "methodology", "reference", "guide"}

    def title_words(t):
        return {w for w in re.findall(r"[a-z0-9]+", t.lower())
                if len(w) > 2 and w not in TITLE_STOP}

    def stem(fn):
        return fn.removesuffix(".md")

    topic_fns = sorted(topic_tags)
    tword = {fn: title_words(topic_titles.get(fn, "")) for fn in topic_fns}
    tset = {fn: set(topic_tags.get(fn, [])) for fn in topic_fns}
    merge_candidate_pairs = []
    for i, a in enumerate(topic_fns):
        for b in topic_fns[i + 1:]:
            sa, sb = stem(a), stem(b)
            slug_prefix = sa.startswith(sb + "-") or sb.startswith(sa + "-")
            shared_title = len(tword[a] & tword[b])
            shared_tags = len(tset[a] & tset[b])
            # The SKILL's confirmation rule requires >=2 shared tags for ANY
            # merge (no slug-prefix exception), so a pair below the tag bar is
            # unmergeable by construction — dropping it here saves the LLM a
            # memory_search per pair (2026-08-22: 9 of 15 emitted pairs were
            # dead on arrival).
            if (slug_prefix or shared_title >= 3) and shared_tags >= 2:
                merge_candidate_pairs.append(
                    {"a": a, "b": b, "slug_prefix": slug_prefix,
                     "shared_tags": shared_tags,
                     "shared_title_words": shared_title})
    merge_candidate_pairs.sort(
        key=lambda p: (not p["slug_prefix"],
                       -(p["shared_tags"] + p["shared_title_words"])))

    return {
        "generated": datetime.date.today().isoformat(),
        "topics_dir": str(topics),
        "inventory": {
            "total": len(files),
            "mocs": sum(1 for c in cls.values() if c == "moc"),
            "dashboards": sum(1 for c in cls.values() if c == "dashboard"),
            "topics": sum(1 for c in cls.values() if c == "topic"),
            "suspect_mocs": sum(1 for c in cls.values() if c == "suspect_moc"),
        },
        "stages": stage_counts,
        "stage_mismatches": stage_mismatches,
        "stage_overstaged": stage_overstaged,
        "broken_links": broken_links,
        "bare_links": bare_links,
        "orphan_topics": orphan_topics,
        "moc_gap_topics": moc_gap_topics,
        "hard_chunks": hard_chunks,
        "soft_chunks": soft_chunks,
        "noncanonical_dated_headers": noncanonical,
        "stale_updated": stale_updated,
        "open_markers": open_markers,
        "open_markers_over_90d": open_markers_over_90d,
        "undated_open_markers": undated_markers,
        "merge_candidate_pairs": merge_candidate_pairs,
        "hub_split_candidates": hub_split,
        "cu_missing": cu_missing,
        "cu_stale": cu_stale,
        "topic_newest_entries": topic_newest_entries,
        "missing_frontmatter": missing_fm,
        "suspect_mocs": sorted(fn for fn, c in cls.items() if c == "suspect_moc"),
        "moc_tags": moc_tags,
        "topic_tags": topic_tags,
        "topic_titles": topic_titles,
    }


def main():
    topics_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/Documents/knowledge-base/topics")
    if not os.path.isdir(topics_dir):
        sys.stderr.write(f"ERROR: topics dir not found: {topics_dir}\n")
        sys.exit(1)
    report = analyze(topics_dir)
    # Namespace the report by input dir, not just date: garden runs analyze.py
    # twice per run (KB topics, then agent-memory topics), and a date-only name
    # made the second run clobber the first before the LLM finished consuming
    # it (observed 2026-06-16 — the agent-memory sweep destroyed the KB report).
    dir_tag = hashlib.sha1(os.path.abspath(topics_dir).encode()).hexdigest()[:8]
    out = os.path.join(tempfile.gettempdir(),
                       f"garden_report_{report['generated']}_{dir_tag}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    inv = report["inventory"]
    sys.stderr.write(
        f"garden analyze: {inv['total']} files "
        f"({inv['topics']} topics, {inv['mocs']} MoCs, {inv['dashboards']} dashboards, "
        f"{inv['suspect_mocs']} suspect MoCs) | "
        f"{len(report['stage_mismatches'])} stage, "
        f"{len(report['stage_overstaged'])} overstaged, "
        f"{len(report['broken_links'])} broken, {len(report['bare_links'])} bare, "
        f"{len(report['orphan_topics'])} orphan, {len(report['moc_gap_topics'])} gap, "
        f"{len(report['soft_chunks'])} soft-chunk, {len(report['hard_chunks'])} hard-chunk, "
        f"{len(report['noncanonical_dated_headers'])} noncanonical-header, "
        f"{len(report['stale_updated'])} stale-updated, "
        f"{len(report['undated_open_markers'])} undated-marker, "
        f"{len(report['open_markers'])} open-marker "
        f"({len(report['open_markers_over_90d'])} over-90d), "
        f"{len(report['merge_candidate_pairs'])} merge-pair, "
        f"{len(report['hub_split_candidates'])} hub-split, "
        f"{len(report['cu_missing'])} cu-missing, {len(report['cu_stale'])} cu-stale\n")
    print(out)


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>")
        sys.exit(0)
    main()
