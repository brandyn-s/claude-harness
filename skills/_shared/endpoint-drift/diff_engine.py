#!/usr/bin/env python3
"""Vendor-agnostic data-channel drift engine (shared by the gather-*-endpoints skills).

Moved from skills/gather-claude-endpoints/scripts/diff_channels.py 2026-08-22;
that path remains as a compatibility shim. A vendor registry is a channel_specs
module (ALL_CHANNELS/BY_KEY plus optional KB_SUBDIR/REPORT_TITLE/OBSERVED_HINT)
loaded via --specs; without --specs the Anthropic registry is the default.

Fetches each channel's authoritative doc page, extracts a normalized fact-set,
and diffs it against the committed baseline in the dedicated knowledge base.
Prints a machine-parseable report and exits non-zero when drift is found, so a
caller can gate on it.

WHY a scripted extractor+diff rather than re-reading prose each run: additions
are salient in prose but REMOVALS are invisible -- nothing in a new doc page
announces the event type that vanished. Only a set-difference against a
committed snapshot catches both directions. And a raw-page diff drowns in prose
rewording, so the signal has to be a normalized fact-set.

Three verdict classes, deliberately distinguished (conflating them is the
documented failure mode -- see verify-effectiveness.md):
  DRIFT            baseline and live differ in the fact-set        -> real signal
  INSTRUMENT_BLIND extraction fell below min_expected              -> DETECTOR bug
  CHANNEL_DEAD     fetch OK but liveness marker missing            -> page rewritten
  FETCH_FAILED     transient/network                               -> retry, not signal

PROVENANCE: this tool asks ONE source (the docs), but a baseline may hold values
learned from a SECOND source -- an observed inventory of what the deployment
actually emits, merged by reconcile_observed.py --observed (Step 2c), which
stamps `observed_source` and lists them in `observed_values`.

An observed-only value is BY DEFINITION absent from the docs, so comparing it
against a docs-only extraction reports it REMOVED on EVERY run, forever. Measured
2026-08-01: 25 phantom REMOVED rows (24 activity types + subagent_completed) on
run 3, all of them values run 2's reconciliation had deliberately added.

That is worse than noise -- it INVERTS the alarm. Both affected fact-sets back
live detectors with CLOSED-SET predicates downstream, so a real vendor rename
BREAKS them; and the differ had already spent its REMOVED signal claiming they
were gone. 25 phantom rows per run also train the reader to dismiss REMOVED,
the class graded HIGHEST.

So values are partitioned by provenance before diffing:
  docs-sourced   -> diffed normally (added/removed are real signal)
  observed-only  -> held out; reported as OBSERVED_ONLY (informational), and
                    flagged only on a state CHANGE: it appeared in the docs
                    (vendor documented it -- promote to docs-sourced), or it
                    stopped being observed (that is reconcile_observed.py's job
                    to detect, since only an observed inventory can see it).

Usage:
  diff_channels.py --kb <kb-dir> [--channel KEY ...] [--update-baseline]
                   [--json OUT] [--offline <dir>]

  --offline <dir>   read <dir>/<channel-key>.md instead of fetching (tests/fixtures)
  --update-baseline write current live fact-sets as the new baseline (after review)

Exit codes: 0 = no drift; 1 = drift found; 2 = instrument/channel problem.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spec_types import ChannelSpec, Extractor  # noqa: E402

# Default vendor registry: the Anthropic channel_specs next to the skill that
# originally housed this engine. Loaded lazily so a --specs run never imports
# it, and so the engine survives environments where the default is absent.
DEFAULT_SPECS_PATH = (
    Path(__file__).resolve().parents[2]
    / "gather-claude-endpoints" / "scripts" / "channel_specs.py"
)


def load_specs(path: Path):
    """importlib-load a vendor registry module from an explicit file path."""
    import importlib.util

    loader_spec = importlib.util.spec_from_file_location("vendor_channel_specs", path)
    if loader_spec is None or loader_spec.loader is None:
        raise ImportError(f"not importable: {path}")
    mod = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(mod)
    missing = [a for a in ("ALL_CHANNELS", "BY_KEY") if not hasattr(mod, a)]
    if missing:
        raise ImportError(f"registry lacks {missing}: {path}")
    return mod


def _bind_registry(mod, specs_path: Path) -> None:
    """Rebind the engine's vendor globals from a loaded registry module."""
    global ALL_CHANNELS, BY_KEY, BASELINE_SUBDIR, REPORT_TITLE, OBSERVED_HINT, SPECS_PATH
    ALL_CHANNELS = mod.ALL_CHANNELS
    BY_KEY = mod.BY_KEY
    BASELINE_SUBDIR = getattr(mod, "KB_SUBDIR", BASELINE_SUBDIR)
    REPORT_TITLE = getattr(mod, "REPORT_TITLE", REPORT_TITLE)
    OBSERVED_HINT = getattr(mod, "OBSERVED_HINT", OBSERVED_HINT)
    SPECS_PATH = specs_path


# Anthropic defaults; _bind_registry overwrites them for --specs runs. Kept as
# import-time state (not None) because tests and the compatibility shim import
# this module and use ALL_CHANNELS/BY_KEY directly.
SPECS_PATH = DEFAULT_SPECS_PATH
try:
    _default_mod = load_specs(DEFAULT_SPECS_PATH)
    ALL_CHANNELS, BY_KEY = _default_mod.ALL_CHANNELS, _default_mod.BY_KEY
except (ImportError, OSError, SyntaxError):  # default registry absent/broken
    ALL_CHANNELS, BY_KEY = (), {}

USER_AGENT = "example-gather-claude-endpoints/1.0 (+internal drift detector)"
TIMEOUT = 45

# Verdict constants -- the parse surface for callers and for the skill's report.
DRIFT = "DRIFT"
CLEAN = "CLEAN"
INSTRUMENT_BLIND = "INSTRUMENT_BLIND"
CHANNEL_DEAD = "CHANNEL_DEAD"
FETCH_FAILED = "FETCH_FAILED"
NO_BASELINE = "NO_BASELINE"
# A manual-export channel whose local file is absent: a standing, known gap.
# Deliberately NOT exit-gating -- an operator-refreshed export being stale must
# not fail every run; it is reported loudly instead.
LOCAL_SOURCE_MISSING = "LOCAL_SOURCE_MISSING"
# A prose Watching trigger deviated from its expectation (a load-bearing
# sentence vanished, or a forbidden token appeared). DRIFT-class for the exit
# code: it is a real vendor-surface state change, not an instrument problem.
TRIGGER_FIRED = "TRIGGER_FIRED"
# Informational, never a problem: the baseline holds values our telemetry saw and
# the docs never listed. Reported so the held-out set is VISIBLE (a silent
# hold-out would be its own coverage lie), but it does not gate the exit code.
OBSERVED_ONLY = "OBSERVED_ONLY"


@dataclass
class ExtractResult:
    key: str
    values: list[str]
    verdict: str
    detail: str = ""


@dataclass
class ChannelResult:
    key: str
    title: str
    url: str
    verdict: str
    detail: str = ""
    extracts: list[ExtractResult] | None = None
    diffs: dict | None = None
    fired_triggers: list[dict] | None = None
    fetched_ok: bool = False  # body retrieved AND liveness marker present


def evaluate_triggers(body: str, spec: ChannelSpec) -> list[dict]:
    """Evaluate the channel's prose Watching triggers on the fetched page.

    These encode the Watching-table rows that are expectations about PROSE
    ("the Bedrock exclusion sentence must stay", "no /v1/ path may appear")
    rather than fact-sets. Before 2026-08-22 they were re-derived by hand every
    run; run 6 alone produced two false zeros from hand greps (case-sensitive
    verbs, a literal `(beta)` against a page that says "in beta"). A trigger
    with a bad regex FIRES rather than silently passing — a broken trigger
    reading as "all clear" is the exact failure this mechanism replaces.
    """
    fired: list[dict] = []
    for t in getattr(spec, "prose_triggers", ()) or ():
        try:
            found = re.search(t.pattern, body, re.MULTILINE) is not None
        except re.error as exc:
            fired.append({"key": t.key, "expect": t.expect,
                          "why": f"bad trigger pattern: {exc}", "note": t.note})
            continue
        if (t.expect == "present") != found:
            why = ("expected pattern PRESENT but it is gone"
                   if t.expect == "present"
                   else "expected pattern ABSENT but it appeared")
            fired.append({"key": t.key, "expect": t.expect, "why": why, "note": t.note})
    return fired


def fetch(url: str) -> tuple[str | None, str]:
    """Return (body, error). Never raises -- transient failure is a distinct class."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace"), ""
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - transient class, reported not raised
        return None, f"{type(exc).__name__}: {exc}"


def extract(body: str, ex: Extractor) -> ExtractResult:
    """Run one extractor. Below min_expected is a DETECTOR bug, not a removal."""
    try:
        rx = re.compile(ex.pattern, re.MULTILINE)
    except re.error as exc:
        return ExtractResult(ex.key, [], INSTRUMENT_BLIND, f"bad pattern: {exc}")

    def canon(value: str) -> str:
        """Apply the extractor's normalize rules to one captured value.

        Runs BEFORE dedup, so two example IDs that canonicalize to the same
        endpoint collapse into one fact instead of two.
        """
        for pat, repl in ex.normalize:
            value = re.sub(pat, repl, value)
        return value

    if ex.kind == "map":
        pairs = {}
        for m in rx.finditer(body):
            if m.lastindex and m.lastindex >= 2:
                pairs[canon(m.group(1))] = m.group(2)
        values = [f"{k}={v}" for k, v in sorted(pairs.items())]
    elif ex.kind == "pair":
        # Every distinct COMBINATION, not one value per key. `map` dedupes by
        # group 1, which is right for "name -> limit" and wrong for verb+path:
        # /apps/chats/files/{id} is declared with BOTH get and delete, and map
        # would keep whichever matched last — silently hiding a DELETE surface.
        values = sorted({
            f"{m.group(1).upper()} {canon(m.group(2))}"
            for m in rx.finditer(body)
            if m.lastindex and m.lastindex >= 2
        })
    else:
        values = sorted({canon(m.group(1)) for m in rx.finditer(body)})

    if len(values) < ex.min_expected:
        return ExtractResult(
            ex.key,
            values,
            INSTRUMENT_BLIND,
            f"extracted {len(values)} < min_expected {ex.min_expected} "
            f"-- treat as extractor blindness (page restructured?), NOT as removal",
        )
    return ExtractResult(ex.key, values, CLEAN)


# Vendor bindings. Defaults are the Anthropic registry this engine shipped with;
# a sibling skill (gather-openai-endpoints) rebinds all three via --specs, which
# loads an alternate channel_specs module carrying its own registry plus optional
# KB_SUBDIR / REPORT_TITLE attributes. The engine itself stays vendor-agnostic:
# every fact-set is just (url, marker, extractors, triggers) + a baseline dir.
BASELINE_SUBDIR = "claude-data-channels"
REPORT_TITLE = "CLAUDE DATA-CHANNEL DRIFT REPORT"
# Rendered under OBSERVED_ONLY; registries override with their own reconcile pointer.
OBSERVED_HINT = "not drift; re-verify these via reconcile_observed.py --observed <inventory>"


def baseline_path(kb: Path, key: str) -> Path:
    return kb / "reference" / BASELINE_SUBDIR / "baselines" / f"{key}.json"


def load_baseline(kb: Path, key: str) -> tuple[list[str], list[str]] | None:
    """Return (docs_sourced, observed_only) for a baseline, or None if absent.

    `observed_values` is the per-value provenance record written by
    reconcile_observed.py. It is REQUIRED to be explicit: a flat
    `observed_source` string says SOME values came from telemetry but not WHICH,
    which is exactly enough information to be unusable -- so a baseline carrying
    `observed_source` with no `observed_values` list is treated as fully
    docs-sourced and will still report phantom removals. That is deliberate: a
    loud wrong answer beats a silent guess at which values to hold out.
    """
    p = baseline_path(kb, key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    values = data.get("values")
    if not isinstance(values, list):
        return None
    observed = data.get("observed_values")
    observed = observed if isinstance(observed, list) else []
    obs_set = set(observed)
    # Held-out set is the INTERSECTION: an observed_values entry that is no longer
    # in `values` is stale bookkeeping and must not create a phantom member.
    held = sorted(obs_set & set(values))
    docs = sorted(set(values) - obs_set)
    return docs, held


def write_baseline(
    kb: Path,
    key: str,
    values: list[str],
    url: str,
    run_date: str,
    observed_values: list[str] | None = None,
) -> Path:
    """Write a baseline, PRESERVING any provenance record already on disk.

    The pre-2026-08-01 writer emitted a fixed 5-key dict, which silently ERASED
    `observed_source`/`observed_values` on every `--update-baseline` -- so the
    docs-only differ could destroy the reconciliation record it was supposed to
    respect. Carry provenance forward explicitly.
    """
    p = baseline_path(kb, key)
    p.parent.mkdir(parents=True, exist_ok=True)

    prior: dict = {}
    if p.exists():
        try:
            prior = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}

    payload: dict = {
        "extractor": key,
        "source_url": url,
        "captured": run_date,
        "count": len(values),
        "values": values,
    }

    observed = observed_values if observed_values is not None else prior.get("observed_values")
    if isinstance(observed, list) and observed:
        # Keep only values still present -- a held-out value the docs now carry has
        # been PROMOTED to docs-sourced and must leave the observed set, or it
        # would be held out of every future diff and never checked again.
        still = sorted(set(observed) & set(values))
        if still:
            payload["observed_values"] = still
            src = prior.get("observed_source")
            payload["observed_source"] = src if src else "live-observed reconciliation"

    p.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p


def process(
    spec: ChannelSpec, kb: Path, offline: Path | None, run_date: str, update: bool,
    pages_dir: Path | None = None,
) -> ChannelResult:
    if offline is not None:
        f = offline / f"{spec.key}.md"
        if not f.exists():
            return ChannelResult(spec.key, spec.title, spec.url, FETCH_FAILED, f"no fixture {f}")
        body = f.read_text(encoding="utf-8", errors="replace")
    elif getattr(spec, "local_path", ""):
        # Manual-export channel: the authoritative page is login-gated, so an
        # operator refreshes a local export. Absence is a standing gap
        # (LOCAL_SOURCE_MISSING), never FETCH_FAILED -- the difference decides
        # the exit code, and an un-refreshed export must not fail the run.
        f = Path(spec.local_path).expanduser()
        if not f.is_absolute():
            # KB-relative export paths follow --kb, so worktree/test KBs read
            # their own exports instead of silently reaching into the home KB.
            f = kb / f
        if not f.exists():
            return ChannelResult(
                spec.key, spec.title, spec.url, LOCAL_SOURCE_MISSING,
                f"manual export absent: {f} -- refresh it from {spec.url} "
                f"(login required); extraction skipped, run not failed")
        body = f.read_text(encoding="utf-8", errors="replace")
    else:
        body, err = fetch(spec.url)
        if body is None:
            return ChannelResult(spec.key, spec.title, spec.url, FETCH_FAILED, err)

    # Persist the fetched page for the run's verification steps (SKILL.md Step 4
    # re-reads these pages to confirm claims in the vendor's words; before
    # 2026-08-22 it re-downloaded multi-MB pages the differ had just fetched).
    if pages_dir is not None:
        try:
            pages_dir.mkdir(parents=True, exist_ok=True)
            (pages_dir / f"{spec.key}.md").write_text(body, encoding="utf-8")
        except OSError as exc:
            print(f"WARNING: could not persist page for {spec.key}: {exc}", file=sys.stderr)

    # Liveness marker: a fetch that returns but misses its marker is a rewritten
    # page (signal), not a quiet vendor. Soft-404s return HTTP 200 with a
    # "Page not found" body, so status code alone proves nothing.
    if spec.marker.lower() not in body.lower():
        return ChannelResult(
            spec.key,
            spec.title,
            spec.url,
            CHANNEL_DEAD,
            f"fetched {len(body)}B but liveness marker {spec.marker!r} absent "
            f"-- page moved/rewritten; re-derive the URL before trusting any diff",
        )

    fired = evaluate_triggers(body, spec)

    extracts: list[ExtractResult] = []
    diffs: dict = {}
    worst = TRIGGER_FIRED if fired else CLEAN

    for ex in spec.extractors:
        res = extract(body, ex)
        extracts.append(res)
        if res.verdict == INSTRUMENT_BLIND:
            worst = INSTRUMENT_BLIND
            continue

        base = load_baseline(kb, ex.key)
        if base is None:
            diffs[ex.key] = {
                "status": NO_BASELINE,
                "live_count": len(res.values),
                "added": [],
                "removed": [],
            }
            if worst == CLEAN:
                worst = NO_BASELINE
            if update:
                write_baseline(kb, ex.key, res.values, spec.url, run_date)
            continue

        docs_base, observed_base = base
        live = set(res.values)

        # Diff against the DOCS-sourced half only. An observed-only value cannot
        # appear in a docs extraction, so including it guarantees a false REMOVED.
        added = sorted(live - set(docs_base) - set(observed_base))
        removed = sorted(set(docs_base) - live)

        # A held-out value the docs NOW carry is a real state change worth naming:
        # the vendor documented something we had only observed. It is not drift
        # (nothing was added or lost), so it is reported separately.
        promoted = sorted(set(observed_base) & live)

        status = DRIFT if (added or removed) else (OBSERVED_ONLY if observed_base else CLEAN)
        diffs[ex.key] = {
            "status": status,
            "baseline_count": len(docs_base) + len(observed_base),
            "docs_baseline_count": len(docs_base),
            "observed_only_count": len(observed_base),
            "live_count": len(res.values),
            "added": added,
            "removed": removed,
            "promoted": promoted,
            "note": ex.note,
        }
        if status == DRIFT and worst in (CLEAN, NO_BASELINE, OBSERVED_ONLY, TRIGGER_FIRED):
            # DRIFT outranks TRIGGER_FIRED as the channel verdict (both are
            # exit-1 class); fired triggers still render from fired_triggers.
            worst = DRIFT
        elif status == OBSERVED_ONLY and worst == CLEAN:
            worst = OBSERVED_ONLY
        if update:
            # Union docs-live with the held-out observed set: writing only the live
            # docs values would DELETE every telemetry-learned value, re-opening
            # the blindness that reconcile_observed.py closed.
            merged = sorted(live | set(observed_base))
            write_baseline(
                kb, ex.key, merged, spec.url, run_date,
                observed_values=sorted(set(observed_base) - live),
            )

    return ChannelResult(spec.key, spec.title, spec.url, worst, "", extracts, diffs,
                         fired_triggers=fired, fetched_ok=True)


def render(results: list[ChannelResult]) -> str:
    out: list[str] = []
    problems = [r for r in results if r.verdict in (FETCH_FAILED, CHANNEL_DEAD, INSTRUMENT_BLIND)]
    # Select by CONTENT, not channel verdict: a channel whose verdict is
    # TRIGGER_FIRED can still carry extractor drift (and vice versa), and
    # keying the section off the verdict would silently drop one of the two.
    drifted = [r for r in results
               if any(d["status"] == DRIFT for d in (r.diffs or {}).values())]
    fired = [r for r in results if r.fired_triggers]
    # By content, not channel verdict: a NEW extractor added to a channel that
    # ALSO drifted this run would otherwise vanish from the NO-BASELINE section
    # (measured live 2026-08-22: otel-trace-spans hid behind otel's DRIFT).
    fresh = [r for r in results
             if any(d["status"] == NO_BASELINE for d in (r.diffs or {}).values())]

    out.append("=" * 72)
    out.append(REPORT_TITLE)
    out.append("=" * 72)
    out.append(
        f"channels: {len(results)}  drift: {len(drifted)}  triggers-fired: {len(fired)}  "
        f"new-baseline: {len(fresh)}  problems: {len(problems)}"
    )
    out.append("")

    if problems:
        out.append("-- INSTRUMENT / CHANNEL PROBLEMS (fix before trusting any diff) --")
        for r in problems:
            out.append(f"  [{r.verdict}] {r.key}: {r.detail or ''}")
            for e in r.extracts or []:
                if e.verdict == INSTRUMENT_BLIND:
                    out.append(f"      extractor {e.key}: {e.detail}")
        out.append("")

    if fired:
        out.append("-- WATCHING TRIGGERS FIRED (prose expectations violated) --")
        for r in fired:
            out.append(f"  {r.key}  ({r.url})")
            for t in r.fired_triggers or []:
                out.append(f"    [{t['key']}] {t['why']}")
                if t.get("note"):
                    out.append(f"      why it matters: {t['note']}")
        out.append("")

    if drifted:
        out.append("-- DRIFT --")
        for r in drifted:
            out.append(f"  {r.key}  ({r.url})")
            for exk, d in (r.diffs or {}).items():
                if d["status"] != DRIFT:
                    continue
                # Report the DOCS-sourced count the diff actually ran against.
                # Printing the combined baseline (docs + held-out) made
                # "39 baseline -> 36 live" read as a 3-value REMOVAL when it
                # was +1 with 4 held out (measured confusion, run 6).
                held = d.get("observed_only_count") or 0
                held_note = f" (+{held} held out)" if held else ""
                out.append(
                    f"    {exk}: {d['docs_baseline_count']} docs-baseline -> "
                    f"{d['live_count']} live{held_note}"
                )
                for v in d["added"]:
                    out.append(f"      + {v}   [NEW]")
                for v in d["removed"]:
                    out.append(f"      - {v}   [REMOVED]")
                if d.get("note"):
                    out.append(f"      why it matters: {d['note']}")
        out.append("")

    if fresh:
        out.append("-- NO BASELINE (first run establishes it; never defer to 'next run') --")
        for r in fresh:
            for exk, d in (r.diffs or {}).items():
                if d["status"] == NO_BASELINE:
                    out.append(f"  {exk}: {d['live_count']} values captured")
        out.append("")

    # Held-out sets are printed even though they are not a problem: a SILENT
    # hold-out would be its own coverage lie -- the reader could not tell a
    # docs-complete fact-set from one carrying N values this tool never checks.
    held = [
        (r, exk, d)
        for r in results
        for exk, d in (r.diffs or {}).items()
        if d.get("observed_only_count")
    ]
    if held:
        out.append("-- OBSERVED_ONLY (in baseline from OUR telemetry; docs never listed them) --")
        for r, exk, d in held:
            out.append(
                f"  {exk}: {d['docs_baseline_count']} docs-sourced diffed, "
                f"{d['observed_only_count']} held out ({r.key})"
            )
            for v in d.get("promoted", []):
                out.append(f"      ^ {v}   [NOW DOCUMENTED -- promote to docs-sourced]")
        out.append(f"      {OBSERVED_HINT}")
        out.append("")

    missing_local = [r for r in results if r.verdict == LOCAL_SOURCE_MISSING]
    if missing_local:
        out.append("-- LOCAL SOURCE MISSING (manual export stale/absent; run NOT failed) --")
        for r in missing_local:
            out.append(f"  [{r.key}] {r.detail}")
        out.append("")

    clean = [r for r in results if r.verdict == CLEAN]
    if clean:
        out.append(f"-- CLEAN ({len(clean)}): " + ", ".join(r.key for r in clean))

    return "\n".join(out)


# Session-scoped freshness cache. Each gate costs a `git fetch` (~2-4 s); two
# vendor skills running in one session pay it four times for identical answers.
# ONLY the FRESH verdict is cached (a cached STALE/UNKNOWN could mask a fix
# made minutes ago, and caching FRESH merely accepts the same race that exists
# during any single run). TTL 15 min; delete the file to force re-checks.
FRESHNESS_CACHE = Path("/tmp/claude/endpoint-drift-freshness.json")
FRESHNESS_TTL_S = 900


def _freshness_cached(key: str, compute) -> tuple[str, str]:
    import time

    now = time.time()
    try:
        cache = json.loads(FRESHNESS_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    ent = cache.get(key)
    if ent and ent.get("status") == "FRESH" and now - ent.get("at", 0) < FRESHNESS_TTL_S:
        return "FRESH", f"{ent.get('detail', '')} [cached {int(now - ent['at'])}s ago]"
    status, detail = compute()
    if status == "FRESH":
        cache[key] = {"status": status, "detail": detail, "at": now}
        try:
            FRESHNESS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            FRESHNESS_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    return status, detail


def _baseline_freshness_uncached(kb: Path) -> tuple[str, str]:
    """Is this KB checkout current with origin/main on the baseline directory?

    WHY THIS EXISTS — measured 2026-08-11 (run 5). The differ reads baselines from
    whatever working tree it is pointed at and never asked whether that tree was
    current. Run 5 was launched against a checkout **35 commits behind
    origin/main**, so it diffed against pre-run-4 baselines and "found" three
    changes run 4 had already shipped (`session.budget_reached`,
    `inference_hooks_request_denied`, the Inference-hooks/App-Attest coverage gap).

    The near-miss is worse than the wasted work: `--update-baseline` on a stale
    tree writes older values back, and committing that tree would have REVERTED
    run 4's 43-file change (824 deletions, including `channels/inference-hooks.md`).
    A drift detector that can silently revert the previous run's findings is
    reporting confidently in the wrong direction — the same failure class as
    finding #12's phantom REMOVED rows, one layer up.

    Returns (status, detail). Status is one of:
      FRESH   — no origin/main commits touch the baseline dir beyond HEAD
      STALE   — origin/main is ahead; the diff and any --update-baseline are unsafe
      UNKNOWN — not a git tree, git unavailable, or the fetch failed

    UNKNOWN is deliberately NOT treated as FRESH. A freshness check whose own
    instrument failed proves nothing, and silently passing is how a stale tree
    gets trusted (verify-before-assuming: absence in a bounded check is a property
    of the check).
    """
    def git(*a: str) -> tuple[int, str]:
        try:
            p = subprocess.run(["git", "-C", str(kb), *a],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, f"{type(exc).__name__}: {exc}"
        return p.returncode, (p.stdout or p.stderr).strip()

    baseline_dir_rel = f"reference/{BASELINE_SUBDIR}"

    rc, _ = git("rev-parse", "--is-inside-work-tree")
    if rc:
        return "UNKNOWN", f"{kb} is not a git work tree — cannot prove baselines are current"

    rc, err = git("fetch", "--quiet", "origin", "main")
    if rc:
        return "UNKNOWN", f"git fetch failed ({err[:120]}) — origin/main ref may itself be stale"

    rc, out = git("rev-list", "--count", "HEAD..origin/main", "--", baseline_dir_rel)
    if rc:
        return "UNKNOWN", f"rev-list failed: {out[:120]}"
    behind = out.strip() or "0"
    if behind != "0":
        rc, log = git("log", "--oneline", "HEAD..origin/main", "--", baseline_dir_rel)
        return "STALE", (
            f"{behind} origin/main commit(s) touch {baseline_dir_rel} and are absent here. "
            f"Diffing this tree re-derives shipped findings, and --update-baseline would "
            f"revert them. Rebase or cut a worktree from origin/main first.\n"
            + "\n".join(f"      {ln}" for ln in log.splitlines()[:10])
        )
    return "FRESH", f"current with origin/main on {baseline_dir_rel}"


def baseline_freshness(kb: Path) -> tuple[str, str]:
    return _freshness_cached(
        f"kb:{kb}:{BASELINE_SUBDIR}", lambda: _baseline_freshness_uncached(kb))


def code_freshness(code_dir: Path | None = None) -> tuple[str, str]:
    """Is the CODE being executed current with origin/main on the skill dir?

    WHY — measured 2026-08-22 (run 6). baseline_freshness() guards the KB tree;
    nothing guarded the code. The live ~/.claude checkout was 143 commits behind
    origin/main, so run 6 initially executed run-5-era scripts: the live
    reconcile leg died on the exact poll-budget bug PR #1960 had already fixed,
    and the differ ran WITHOUT the baseline-freshness gate at all. A skill that
    self-hardens each run silently sheds those fixes when the runtime tree lags
    — finding #27's mechanism, one layer up.

    Statuses mirror baseline_freshness, with one deliberate difference: UNKNOWN
    here WARNS and proceeds instead of refusing. The baseline gate protects
    WRITES to the KB (a stale write reverts the prior run); this gate protects
    the run's own instruments, and the code legitimately runs from non-git
    copies (a marketplace install, a tarball). STALE still refuses: the fix for
    stale code is one worktree command, and running anyway reproduces already-
    fixed bugs as fresh findings.

    Generalized 2026-08-22: takes the code dir to check (default: the engine's
    own dir). main() also checks the --specs registry's dir — a stale registry
    on a current engine previously passed this gate unexamined.
    """
    here = (code_dir or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    return _freshness_cached(f"code:{here}", lambda: _code_freshness_uncached(here))


def _code_freshness_uncached(here: Path) -> tuple[str, str]:

    def git(*a: str) -> tuple[int, str]:
        try:
            p = subprocess.run(["git", "-C", str(here), *a],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, f"{type(exc).__name__}: {exc}"
        return p.returncode, (p.stdout or p.stderr).strip()

    rc, _ = git("rev-parse", "--is-inside-work-tree")
    if rc:
        return "UNKNOWN", "not running from a git work tree — code currency unprovable"

    rc, top = git("rev-parse", "--show-toplevel")
    if rc:
        return "UNKNOWN", f"rev-parse --show-toplevel failed: {top[:120]}"
    try:
        rel = str(here.relative_to(Path(top)))
    except ValueError:
        rel = "."

    rc, err = git("fetch", "--quiet", "origin", "main")
    if rc:
        return "UNKNOWN", f"git fetch failed ({err[:120]}) — origin/main ref may be stale"

    rc, out = git("rev-list", "--count", "HEAD..origin/main", "--", rel)
    if rc:
        return "UNKNOWN", f"rev-list failed: {out[:120]}"
    behind = out.strip() or "0"
    if behind != "0":
        rc, log = git("log", "--oneline", "HEAD..origin/main", "--", rel)
        return "STALE", (
            f"{behind} origin/main commit(s) touch {rel} and are absent from "
            f"the running copy. Run from a current worktree instead:\n"
            f"      git -C <repo> worktree add --detach /tmp/claude/ccwt origin/main\n"
            + "\n".join(f"      {ln}" for ln in log.splitlines()[:10])
        )
    return "FRESH", f"running code is current with origin/main on {rel}"


def update_sources_log(kb: Path, results: list[ChannelResult], run_date: str) -> list[str]:
    """Bump each successfully-fetched channel's 'Last OK' date in INTELLIGENCE.md.

    The Sources Log is per-channel BY DESIGN (a channel that fails one run
    re-scans its own gap next run), which made it 26 hand-edited table rows per
    run. This bumps ONLY the date column of channels that fetched OK this run
    (body retrieved AND liveness marker present); notes columns are narrative
    and stay untouched.

    Returns the channel keys that fetched OK but have NO row — run 5 measured
    that the log had silently omitted 8 registered channels, making an
    incomplete log look like the coverage list. Missing rows are reported,
    never silently created: the notes column needs a human sentence.
    """
    intel = kb / "reference" / BASELINE_SUBDIR / "INTELLIGENCE.md"
    if not intel.exists():
        return []
    text = intel.read_text(encoding="utf-8")
    missing: list[str] = []
    for r in results:
        if not r.fetched_ok:
            continue
        row_rx = re.compile(
            rf"^(\| `{re.escape(r.key)}` \| )\d{{4}}-\d{{2}}-\d{{2}}( \|)", re.MULTILINE)
        new_text, n = row_rx.subn(rf"\g<1>{run_date}\g<2>", text)
        if n == 0:
            missing.append(r.key)
        else:
            text = new_text
    intel.write_text(text, encoding="utf-8")
    return missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kb", default=str(Path.home() / "Documents" / "knowledge-base"))
    ap.add_argument("--channel", action="append", default=None, help="limit to channel key(s)")
    ap.add_argument("--offline", default=None, help="fixture dir instead of network")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--json", default=None, help="write machine-readable results here")
    ap.add_argument("--run-date", default=None, help="YYYY-MM-DD stamp for baselines")
    ap.add_argument("--list", action="store_true", help="list channels and exit")
    ap.add_argument("--allow-stale-baselines", action="store_true",
                    help="proceed even if the KB checkout is behind origin/main on the "
                         "baseline dir (offline/fixture runs); never use with --update-baseline")
    ap.add_argument("--allow-stale-code", action="store_true",
                    help="proceed even if the RUNNING copy of this skill is behind "
                         "origin/main (run 6 executed 143-commit-stale code and "
                         "reproduced an already-fixed bug); prefer a fresh worktree")
    ap.add_argument("--pages-dir", default=None,
                    help="persist each fetched page as <dir>/<channel>.md for the "
                         "run's verification steps; defaults to <json-path>-pages/ "
                         "when --json is given, pass '' to disable")
    ap.add_argument("--update-sources-log", action="store_true",
                    help="bump fetched-OK channels' Last-OK dates in the KB's "
                         "INTELLIGENCE.md Sources Log (implied by --update-baseline)")
    ap.add_argument("--specs", default=None,
                    help="path to an alternate channel_specs .py file (a vendor "
                         "registry: ALL_CHANNELS/BY_KEY, optional KB_SUBDIR and "
                         "REPORT_TITLE). Used by sibling skills, e.g. "
                         "gather-openai-endpoints; default is the Anthropic "
                         "registry next to this script")
    args = ap.parse_args(argv)

    if args.specs:
        specs_path = Path(args.specs).expanduser().resolve()
        if not specs_path.exists():
            print(f"--specs file not found: {specs_path}", file=sys.stderr)
            return 2
        try:
            _bind_registry(load_specs(specs_path), specs_path)
        except (ImportError, OSError, SyntaxError) as exc:
            print(f"--specs load failed: {exc}", file=sys.stderr)
            return 2
    elif not ALL_CHANNELS:
        print(f"default registry unavailable ({DEFAULT_SPECS_PATH}); pass --specs",
              file=sys.stderr)
        return 2

    if args.list:
        for c in ALL_CHANNELS:
            print(f"{c.key:32s} {c.surface:12s} {c.url}")
            for e in c.extractors:
                print(f"    - {e.key} (min {e.min_expected})")
        return 0

    kb = Path(args.kb).expanduser()

    # Freshness gates BEFORE any diff. A stale baseline makes every verdict on this
    # page wrong in the most misleading direction, and --update-baseline on a stale
    # tree reverts the previous run; stale CODE re-runs already-fixed instrument
    # bugs as fresh findings (run 6). --offline runs read fixtures, not the KB's
    # live baselines, so both gates are exempt there.
    if not args.offline:
        # Two code surfaces can each be stale independently: the engine (this
        # file) and the vendor registry named by --specs. A stale registry on a
        # current engine previously passed unexamined.
        for gate_dir in {Path(__file__).resolve().parent, SPECS_PATH.parent}:
            code_status, code_detail = code_freshness(gate_dir)
            if code_status == "STALE" and not args.allow_stale_code:
                print(f"[CODE_STALE] {code_detail}", file=sys.stderr)
                print("refusing to run stale instruments; re-run from an origin/main "
                      "worktree, or pass --allow-stale-code", file=sys.stderr)
                return 2
            if code_status != "FRESH":
                print(f"[CODE_{code_status}] {code_detail}", file=sys.stderr)

        fresh_status, fresh_detail = baseline_freshness(kb)
        if fresh_status != "FRESH":
            print(f"[BASELINE_{fresh_status}] {fresh_detail}", file=sys.stderr)
            if not args.allow_stale_baselines:
                print("refusing to diff against baselines that are not proven current; "
                      "pass --allow-stale-baselines to override (never with "
                      "--update-baseline)", file=sys.stderr)
                return 2
            if args.update_baseline:
                print("REFUSING --update-baseline with unproven baseline freshness: writing "
                      "would revert newer values.", file=sys.stderr)
                return 2

    offline = Path(args.offline).expanduser() if args.offline else None
    # Date is passed in (never computed) so the script stays deterministic and
    # resume-safe; the caller stamps it.
    run_date = args.run_date or "unknown"

    specs = ALL_CHANNELS
    if args.channel:
        missing = [k for k in args.channel if k not in BY_KEY]
        if missing:
            print(f"unknown channel key(s): {missing}", file=sys.stderr)
            return 2
        specs = tuple(BY_KEY[k] for k in args.channel)

    # Pages dir: derived from --json unless overridden ('' disables). Persisted
    # pages let Step 4 verification re-read what the differ fetched instead of
    # re-downloading multi-MB pages.
    pages_dir: Path | None = None
    if args.pages_dir == "":
        pages_dir = None
    elif args.pages_dir:
        pages_dir = Path(args.pages_dir).expanduser()
    elif args.json and not args.offline:
        jp = Path(args.json).expanduser()
        pages_dir = jp.parent / (jp.stem + "-pages")

    results = [process(s, kb, offline, run_date, args.update_baseline, pages_dir)
               for s in specs]
    print(render(results))
    if pages_dir is not None:
        print(f"\nfetched pages persisted to: {pages_dir}")

    if args.update_baseline or args.update_sources_log:
        missing_rows = update_sources_log(kb, results, run_date)
        if missing_rows:
            print(f"WARNING: Sources Log has NO row for fetched-OK channel(s) "
                  f"{missing_rows} — add rows so the log matches the registry "
                  f"(run 5 found 8 silently missing)", file=sys.stderr)

    if args.json:
        Path(args.json).expanduser().write_text(
            json.dumps(
                [
                    {
                        "channel": r.key,
                        "url": r.url,
                        "verdict": r.verdict,
                        "detail": r.detail,
                        "diffs": r.diffs or {},
                        "fired_triggers": r.fired_triggers or [],
                    }
                    for r in results
                ],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    if any(r.verdict in (FETCH_FAILED, CHANNEL_DEAD, INSTRUMENT_BLIND) for r in results):
        return 2
    if any(r.verdict == DRIFT or r.fired_triggers for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
