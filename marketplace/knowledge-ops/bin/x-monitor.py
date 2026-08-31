#!/usr/bin/env python3
"""x-monitor: on-demand X (Twitter) perception + adversarial monitoring.

v2 (2026-06-13): structured-output intelligence pipeline. Every xAI query
returns a strict-JSON envelope (narrative + per-post findings + actionable
items + empty queries) so findings persist machine-readable in the state
file, with engagement history per post. New: copy-chain + author-expansion
second passes, multi-phrasing EN adversarial, recheck mode (engagement
velocity on tracked negatives), consolidate mode (local tiered collection),
per-run cost telemetry (usage.cost_in_usd_ticks / 1e10 = USD), Turkish +
Hindi adversarial languages, excluded_x_handles plumbing, --model override,
experimental --batch (xAI Batch API, ~half token cost, async). Exa removed
from web sweeps (returned zero X-scoped hits — ignores includeDomains).

Dual-instrument design:
  1. Native ranked search — xAI Responses API with the server-side x_search
     agentic tool. Best for narrative synthesis, thread fetch, engagement
     counts, multilingual sweeps, handle-locked probes.
  2. Flat web-index sweeps — Tavily / Firecrawl REST, domain-scoped to
     x.com. Catches low-engagement posts that ranked search buries
     (verified failure mode: 2x retrieval misses on 2026-06-12).

Delta-flagging: every x.com status ID seen in any run is recorded in the
state file; reports flag NEW posts vs previously-seen. Findings (negative /
controversial posts) additionally persist with category, severity, and an
engagement-history series enabling velocity alerts and watchlist-candidate
suggestions (handles with repeat negative finds).

Usage:
  x-monitor.py --mode full                  # subjects + adversarial + watchlists
  x-monitor.py --mode subjects              # consensus per configured subject
  x-monitor.py --mode adversarial           # negative-only sweeps, EN x3 + per-language
  x-monitor.py --mode watchlist             # handle-locked probes (critics, state media)
  x-monitor.py --mode event --query "..."   # focused deep-dive on one event
  x-monitor.py --mode recheck               # re-probe tracked negatives, flag velocity
  x-monitor.py --mode consolidate --days 30 # local: tiered collection from state
  x-monitor.py --smoke                      # cheap end-to-end validation run
  Options: --from-date/--to-date (ISO), --no-web, --no-second-pass,
           --model <id>, --batch (async Batch API), --config <path>

Keys: resolved env-var-first, then macOS Keychain generic passwords with
service names XAI_API_KEY / TAVILY_API_KEY / FIRECRAWL_API_KEY.
Values are never printed.

Outputs (machine-local, intentionally outside any git repo):
  ~/Documents/x-monitor/reports/<UTC ts>-x-monitor-<mode>.md
  ~/Documents/x-monitor/state/seen_posts.json

INTERRUPTION: safe — the report file is written before the state file is
updated (atomic os.replace), so a killed run never marks posts as seen
without a report that contains them. Re-running after interruption
re-reports the same posts as NEW, which is the correct failure direction
for monitoring. Batch mode: an interrupted poll loses nothing server-side;
the printed batch_id can be re-polled manually.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

XAI_URL = "https://api.x.ai/v1/responses"
XAI_BATCHES_URL = "https://api.x.ai/v1/batches"
TAVILY_URL = "https://api.tavily.com/search"
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/search"

BASE_DIR = os.path.expanduser("~/Documents/x-monitor")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
STATE_PATH = os.path.join(BASE_DIR, "state", "seen_posts.json")
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "x-monitor.config.json")

STATUS_ID_RE = re.compile(r"(?:x|twitter)\.com/(?:[A-Za-z0-9_]+|i)/status(?:es)?/(\d{8,25})")
INLINE_CITE_RE = re.compile(r"\[\[\d+\]\]\((https?://[^)\s]+)\)")
HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{1,15})")

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}

# ── prompt templates ─────────────────────────────────────────────────────────
# __SLOT__ tokens with .replace(), never str.format (braces appear in example
# queries and would KeyError).

COMMON_RULES = (
    "Rules: report ONLY what real X posts say — never extrapolate. Write your full "
    "analytical report (markdown) in the `narrative` field. Put EVERY post you cite into "
    "the `findings` array with handle, post URL, date, engagement counts where visible, a "
    "short exact quote, a category, a severity, the subject it targets, and is_negative. "
    "FETCH AND READ THE FULL REPLY THREADS under the 2-3 highest-engagement posts and "
    "summarize reply sentiment in the narrative; hostile or notable REPLIES are findings "
    "too. Low-engagement posts (0-10 likes) matter as much as viral ones. List anything "
    "implying a follow-up by the monitored company (broken promises, unanswered critics, "
    "correction-worthy media errors) in `actionable_items`. If a category has zero "
    "results, say so in the narrative and list the exact searches you tried that came "
    "back empty in `empty_queries`."
)

SUBJECT_TMPL = (
    "Search X extensively (multiple phrasings) for posts about __SUBJECT__. "
    "Summarize in the narrative: (1) overall consensus and sentiment balance, (2) main "
    "themes with representative posts, (3) named critics or skeptics and their arguments, "
    "(4) who drives the conversation, (5) reply-thread sentiment under the top posts. "
    + COMMON_RULES
)

# Multi-phrasing: three differently-angled EN adversarial sweeps. Evidence
# (2026-06-12): a single-phrasing products query containing "boat-not-ship"
# returned zero while a handle-locked probe surfaced a 95K-view critical
# thread — ranked search under-recalls on any one phrasing.
ADV_EN_TMPLS = [
    (
        "ADVERSARIAL-ONLY keyword sweep about __SUBJECTS__. Find ONLY negative, hostile, "
        "skeptical, mocking, or counter-narrative posts — ignore praise and neutral "
        "reporting. Run many separate negative-keyword searches: overhyped, grift, bubble, "
        "overvalued, staged, psyop, propaganda, fake, scam, war profiteers, lobbying, "
        "protest, crash, collision, failure, fraud, 'boat not ship'. Also search "
        "isolationist/anti-war angles and identity-focused negativity about the founders. "
        "Group findings by category in the narrative. " + COMMON_RULES
    ),
    (
        "ADVERSARIAL discourse sweep about __SUBJECTS__. Find sustained criticism from "
        "CREDIBLE or influential accounts: domain experts, journalists, maritime or "
        "defense professionals, investors, or large accounts challenging the company's "
        "claims, messaging, valuation, products, or leadership — including measured, "
        "non-hostile criticism with real engagement. Search for debate threads, "
        "quote-post pile-ons, and fact-check or correction posts. Ignore praise. "
        + COMMON_RULES
    ),
    (
        "ADVERSARIAL reply-mining sweep about __SUBJECTS__. Find the highest-engagement "
        "posts about these subjects from the window, then READ THEIR REPLY THREADS and "
        "quote-posts hunting for hostile, mocking, conspiratorial, or identity-attack "
        "replies — negative replies under viral positive posts are the primary target. "
        "Ignore the positive top-level posts themselves except as thread anchors. "
        + COMMON_RULES
    ),
]

ADV_LANG_TMPL = (
    "ADVERSARIAL-ONLY sweep in __LANGUAGE__ about __SUBJECTS__. Search X using "
    "native-script __LANGUAGE__ queries only (examples: __EXAMPLES__) for hostile, "
    "mocking, conspiratorial, or state-aligned counter-narrative posts. Ignore praise "
    "entirely. Translate each finding to English alongside the original text in the "
    "narrative; quotes in findings may stay in the original script. " + COMMON_RULES
)

WATCHLIST_TMPL = (
    "Your X search tool is restricted to posts from exactly these accounts: __HANDLES__. "
    "Search each of these handles directly (from:<handle> style and semantic queries "
    "scoped to them — do NOT search for other accounts; they are filtered out). Report "
    "EVERYTHING these accounts posted in the search window about __TOPICS__. Every "
    "relevant post goes in findings verbatim with date and URL. If they posted nothing "
    "on these topics, say so explicitly in the narrative and summarize in one paragraph "
    "what they posted about instead. " + COMMON_RULES
)

EVENT_TMPL = (
    "Deep-dive the X discourse about: __EVENT__. Cover in the narrative: (1) timeline — "
    "who broke it, which posts went viral with engagement counts, how it evolved; "
    "(2) reaction by segment (journalists, military/OSINT, veterans, VCs, political, "
    "foreign/adversarial accounts); (3) skepticism, corrections, wrong-media callouts, "
    "and counter-narratives; (4) the most substantive analytical threads. " + COMMON_RULES
)

COPYCHAIN_TMPL = (
    "Provenance trace. For EACH quoted text below, search X for posts containing the "
    "exact text or close paraphrases. Identify the ORIGINAL (earliest) post and every "
    "copy or quote-repost, with engagement counts for each. All located posts go in "
    "findings; prefix the quote field with '[ORIGINAL] ' or '[COPY] ' accordingly. "
    "Quotes to trace:\n__QUOTES__\n" + COMMON_RULES
)

AUTHOR_EXPAND_TMPL = (
    "Your X search tool is restricted to posts from exactly these accounts: __HANDLES__. "
    "These accounts each posted negative or controversial content about __SUBJECTS__. "
    "For each handle, report what ELSE they posted in the window about these subjects, "
    "how often they post negatively about them, their approximate follower scale, and "
    "whether the negativity looks persistent (campaign) or drive-by (one-off). Every "
    "relevant post goes in findings. " + COMMON_RULES
)

RECHECK_PROMPT = (
    "Engagement recheck. For EACH X post URL below, fetch the post and report its "
    "CURRENT engagement counts (likes, reposts, views). If a post is deleted, "
    "unavailable, or from a suspended account, mark it deleted. Do not search for "
    "anything else.\n__URLS__"
)

# ── structured output schemas (strict mode: all properties required,
#    additionalProperties false, nullability via type unions) ────────────────

FINDING_CATEGORIES = [
    "staged_conspiracy", "identity_attack", "valuation_criticism",
    "messaging_criticism", "media_accuracy", "counter_narrative",
    "leak_disclosure", "doxxing", "mockery", "employee_complaint",
    "state_aligned", "other_negative", "neutral_context",
]

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {
            "type": "string",
            "description": "The full analytical report in markdown, same depth as a standalone writeup.",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "Author handle without @"},
                    "url": {"type": "string", "description": "Full x.com post URL"},
                    "date": {"type": "string", "description": "Post date, ISO or as shown"},
                    "quote": {"type": "string", "description": "Short exact quote from the post"},
                    "likes": {"type": ["integer", "null"]},
                    "reposts": {"type": ["integer", "null"]},
                    "views": {"type": ["integer", "null"]},
                    "category": {"type": "string", "enum": FINDING_CATEGORIES},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "target": {"type": "string", "description": "Company, product, or person the post is about"},
                    "is_negative": {"type": "boolean"},
                },
                "required": ["handle", "url", "date", "quote", "likes", "reposts",
                             "views", "category", "severity", "target", "is_negative"],
                "additionalProperties": False,
            },
        },
        "actionable_items": {"type": "array", "items": {"type": "string"}},
        "empty_queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative", "findings", "actionable_items", "empty_queries"],
    "additionalProperties": False,
}

RECHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "likes": {"type": ["integer", "null"]},
                    "reposts": {"type": ["integer", "null"]},
                    "views": {"type": ["integer", "null"]},
                    "deleted": {"type": "boolean"},
                },
                "required": ["url", "likes", "reposts", "views", "deleted"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["posts"],
    "additionalProperties": False,
}


def text_format(name: str, schema: dict) -> dict:
    return {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}


# ── key + state + http plumbing ──────────────────────────────────────────────

def resolve_key(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    r = subprocess.run(
        ["security", "find-generic-password", "-s", name, "-w"],
        capture_output=True,
    )
    return r.stdout.decode("utf-8", errors="replace").strip()


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("seen", {})
    state.setdefault("findings", {})  # v2: post_key -> finding record
    return state


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def http_json(url: str, headers: dict, body: dict | None = None, timeout: int = 600,
              method: str | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **headers},
        method=method or ("POST" if body is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


# ── native xAI side ──────────────────────────────────────────────────────────

def usage_of(resp: dict) -> dict:
    u = resp.get("usage") or {}
    return {
        "cost_usd": (u.get("cost_in_usd_ticks") or 0) / 1e10,
        "tools_used": u.get("num_server_side_tools_used") or 0,
        "total_tokens": u.get("total_tokens") or 0,
    }


def parse_structured(resp: dict):
    """Return (payload_dict_or_None, raw_text, cited_urls, encountered_urls, usage)."""
    texts, cited = [], []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
                    for ann in part.get("annotations", []) or []:
                        if ann.get("type") == "url_citation" and ann.get("url"):
                            cited.append(ann["url"])
    raw = "\n".join(texts)
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            payload = None
    except (json.JSONDecodeError, ValueError):
        payload = None  # fail-soft: caller falls back to narrative-only
    cited.extend(INLINE_CITE_RE.findall(payload.get("narrative", "") if payload else raw))
    encountered = [c for c in resp.get("citations", []) or [] if isinstance(c, str)]
    seen = set()
    cited = [c for c in cited if not (c in seen or seen.add(c))]
    return payload, raw, cited, encountered, usage_of(resp)


def build_body(prompt: str, tool_params: dict, model: str, schema_name: str = "x_monitor_findings",
               schema: dict | None = None) -> dict:
    return {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "tools": [{"type": "x_search", **tool_params}],
        "text": text_format(schema_name, schema or FINDINGS_SCHEMA),
    }


def result_from_response(resp: dict) -> dict:
    payload, text, cited, encountered, usage = parse_structured(resp)
    if payload is None:
        payload = {"narrative": text, "findings": [], "actionable_items": [],
                   "empty_queries": []}
        usage["parse_fallback"] = True
    payload.setdefault("findings", [])
    payload.setdefault("actionable_items", [])
    payload.setdefault("empty_queries", [])
    return {"ok": True, "payload": payload, "cited": cited,
            "encountered": encountered, "usage": usage}


def xai_query(key: str, name: str, body: dict):
    try:
        raw = http_json(XAI_URL, {"Authorization": f"Bearer {key}"}, body)
        return name, result_from_response(raw)
    except urllib.error.HTTPError as e:
        return name, {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:800]}"}
    except Exception as e:  # noqa: BLE001 — one query failing must not kill the run
        return name, {"ok": False, "error": f"{type(e).__name__}: {e}"}


def run_xai_jobs(key: str, jobs: list, model: str, use_batch: bool, batch_timeout: int):
    """jobs: [(name, prompt, tool_params)] -> {name: result}. Sync pool or Batch API."""
    bodies = {n: build_body(p, t, model) for n, p, t in jobs}
    if use_batch:
        return run_batch(key, bodies, batch_timeout)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(xai_query, key, n, b) for n, b in bodies.items()]
        for fut in concurrent.futures.as_completed(futs):
            name, result = fut.result()
            results[name] = result
            cost = result.get("usage", {}).get("cost_usd", 0) if result.get("ok") else 0
            print(f"  [{name}] {'OK $%.3f' % cost if result['ok'] else 'FAIL: ' + result['error'][:120]}",
                  flush=True)
    return results


# ── Batch API (experimental; docs: ~half token cost, async; for
#    non-interactive sweeps where latency is irrelevant) ─────────────────────

def run_batch(key: str, bodies: dict, timeout: int):
    hdr = {"Authorization": f"Bearer {key}"}
    batch = http_json(XAI_BATCHES_URL, hdr,
                      {"name": "x-monitor-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")})
    batch_id = batch.get("batch_id") or batch.get("id")
    if not batch_id:
        return {n: {"ok": False, "error": f"batch create returned no id: {json.dumps(batch)[:300]}"}
                for n in bodies}
    reqs = [{"batch_request_id": name, "batch_request": {"responses": body}}
            for name, body in bodies.items()]
    http_json(f"{XAI_BATCHES_URL}/{batch_id}/requests", hdr, {"batch_requests": reqs})
    print(f"  [batch] {batch_id} submitted ({len(reqs)} requests); polling every 30s "
          f"(timeout {timeout}s)", flush=True)
    deadline = time.time() + timeout
    while True:
        st = http_json(f"{XAI_BATCHES_URL}/{batch_id}", hdr)
        s = st.get("state", {})
        pending = s.get("num_pending", 0)
        print(f"  [batch] pending={pending} success={s.get('num_success', 0)} "
              f"error={s.get('num_error', 0)}", flush=True)
        if pending == 0:
            break
        if time.time() > deadline:
            print(f"  [batch] TIMEOUT — re-poll manually: batch_id={batch_id}", flush=True)
            return {n: {"ok": False, "error": f"batch timeout; batch_id={batch_id}"} for n in bodies}
        time.sleep(30)
    results, token = {}, None
    while True:
        url = f"{XAI_BATCHES_URL}/{batch_id}/results?limit=100"
        if token:
            url += f"&pagination_token={urllib.parse.quote(token)}"
        page = http_json(url, hdr)
        for r in page.get("results", []):
            name = r.get("batch_request_id", "?")
            container = (r.get("batch_result") or {}).get("response") or {}
            # Defensive: docs pin chat results to `chat_get_completion` but do
            # not name the Responses-endpoint key — accept any dict carrying
            # an `output` list.
            resp = container if "output" in container else next(
                (v for v in container.values() if isinstance(v, dict) and "output" in v), None)
            if resp is None:
                err = r.get("error_message") or f"unrecognized batch result shape: {str(r)[:300]}"
                results[name] = {"ok": False, "error": err}
                continue
            results[name] = result_from_response(resp)
        token = page.get("pagination_token")
        if not token:
            break
    for n in bodies:
        results.setdefault(n, {"ok": False, "error": "missing from batch results"})
    return results


# ── job builders ─────────────────────────────────────────────────────────────

def media_params(cfg: dict) -> dict:
    media = {}
    if cfg.get("image_understanding", True):
        media["enable_image_understanding"] = True
    if cfg.get("video_understanding", True):
        media["enable_video_understanding"] = True
    return media


def broad_params(cfg: dict, window: dict) -> dict:
    """Window + media + excluded handles for non-handle-locked sweeps.
    excluded_x_handles cannot combine with allowed_x_handles (vendor rule)."""
    p = {**window, **media_params(cfg)}
    excluded = [h for h in cfg.get("excluded_x_handles", []) if h][:20]
    if excluded:
        p["excluded_x_handles"] = excluded
    return p


def build_xai_jobs(cfg: dict, mode: str, window: dict, args) -> list:
    jobs = []
    subjects = cfg["subjects"]
    if args.subject:
        subjects = [s for s in subjects if s["id"] == args.subject]
    subj_names = ", ".join(s["search_name"] for s in cfg["subjects"])
    bp = broad_params(cfg, window)
    wp = {**window, **media_params(cfg)}  # watchlists: allowed_x_handles only

    if mode in ("full", "subjects"):
        for s in subjects:
            jobs.append((f"subject:{s['id']}",
                         SUBJECT_TMPL.replace("__SUBJECT__", s["search_name"]), bp))
    if mode in ("full", "adversarial"):
        for i, tmpl in enumerate(ADV_EN_TMPLS, 1):
            jobs.append((f"adversarial:en{i}",
                         tmpl.replace("__SUBJECTS__", subj_names), bp))
        for lang in cfg.get("adversarial_languages", []):
            jobs.append((f"adversarial:{lang['code']}",
                         ADV_LANG_TMPL.replace("__LANGUAGE__", lang["name"])
                                      .replace("__EXAMPLES__", lang["examples"])
                                      .replace("__SUBJECTS__", subj_names), bp))
    if mode in ("full", "watchlist"):
        for group, spec in cfg.get("watchlists", {}).items():
            handles = spec["handles"][:20]
            jobs.append((f"watchlist:{group}",
                         WATCHLIST_TMPL.replace("__HANDLES__", ", ".join("@" + h for h in handles))
                                       .replace("__TOPICS__", spec["topics"]),
                         {**wp, "allowed_x_handles": handles}))
    if mode == "event":
        jobs.append(("event", EVENT_TMPL.replace("__EVENT__", args.query or ""), bp))
    return jobs


def watched_handles(cfg: dict) -> set:
    """Handles already covered: watchlists + any @handle in subject names."""
    covered = set()
    for spec in cfg.get("watchlists", {}).values():
        covered.update(h.lower() for h in spec["handles"])
    for s in cfg.get("subjects", []):
        covered.update(h.lower() for h in HANDLE_RE.findall(s["search_name"]))
    return covered


def second_pass_jobs(cfg: dict, window: dict, new_negatives: list) -> list:
    """Copy-chain + author-expansion follow-ups from this run's NEW negative
    findings. Evidence (2026-06-12): broad sweep found a 3-like copy of an
    identity post; the 233-like ORIGINAL surfaced only via a handle-locked
    probe. Provenance tracing closes that gap mechanically."""
    jobs = []
    subj_names = ", ".join(s["search_name"] for s in cfg["subjects"])
    quotes, seen_q = [], set()
    for f in new_negatives:
        if f.get("severity") in ("high", "medium"):
            q = (f.get("quote") or "").strip()[:200]
            if len(q) >= 25 and q not in seen_q:
                seen_q.add(q)
                quotes.append(q)
    if quotes:
        block = "\n".join(f'- "{q}"' for q in quotes[:5])
        jobs.append(("second:copy-chain",
                     COPYCHAIN_TMPL.replace("__QUOTES__", block),
                     broad_params(cfg, window)))
    covered = watched_handles(cfg)
    authors = []
    for f in new_negatives:
        h = (f.get("handle") or "").lstrip("@")
        if h and h.lower() not in covered and h not in authors:
            authors.append(h)
    if authors:
        jobs.append(("second:author-expansion",
                     AUTHOR_EXPAND_TMPL.replace("__HANDLES__", ", ".join("@" + h for h in authors[:20]))
                                       .replace("__SUBJECTS__", subj_names),
                     {**window, **media_params(cfg), "allowed_x_handles": authors[:20]}))
    return jobs


# ── flat web-index side (Tavily + Firecrawl; Exa removed 2026-06-13 — zero
#    X-scoped hits across all 2026-06-12 runs, ignores includeDomains) ───────

def web_sweeps(cfg: dict, keys: dict, smoke: bool, event_query: str | None = None):
    if event_query:
        queries = [event_query[:380]]  # Tavily rejects queries >= 400 chars
    else:
        queries = []
        subjects = cfg["subjects"][:1] if smoke else cfg["subjects"]
        for s in subjects:
            queries.append(s["web_query"])
        if not smoke:
            queries.extend(cfg.get("web_adversarial_queries", []))

    results = {"tavily": [], "firecrawl": [], "errors": []}

    def tavily(q):
        return http_json(TAVILY_URL, {"Authorization": f"Bearer {keys['TAVILY_API_KEY']}"},
                         {"query": q, "include_domains": ["x.com", "twitter.com"],
                          "search_depth": "advanced", "max_results": 5}, timeout=60)

    def firecrawl(q):
        return http_json(FIRECRAWL_URL, {"Authorization": f"Bearer {keys['FIRECRAWL_API_KEY']}"},
                         {"query": f"site:x.com {q}", "limit": 5}, timeout=60)

    def fc_pick(r):
        # REST v1 returns data as a LIST; the MCP (v2-style) nests it as
        # {data: {web: [...]}} — handle both (caught by smoke run 2026-06-12).
        data = r.get("data")
        items = data.get("web", []) if isinstance(data, dict) else (data or [])
        return [(x.get("url", ""), x.get("title", "")) for x in items if isinstance(x, dict)]

    for q in queries:
        for provider, fn, picker in (
            ("tavily", tavily, lambda r: [(x.get("url", ""), x.get("title", "")) for x in r.get("results", [])]),
            ("firecrawl", firecrawl, fc_pick),
        ):
            if not keys.get(f"{provider.upper()}_API_KEY"):
                continue
            try:
                hits = picker(fn(q))
                # Providers don't reliably honor domain filters — enforce the
                # X scope client-side; non-X hits are counted only.
                x_hits = [(u, t) for u, t in hits if re.search(r"(?:x|twitter)\.com/", u)]
                results[provider].append({"query": q, "hits": x_hits,
                                          "non_x": len(hits) - len(x_hits)})
            except Exception as e:  # noqa: BLE001 — provider down ≠ run failure
                results["errors"].append(f"{provider} [{q[:50]}]: {type(e).__name__}: {e}")
    return results


# ── findings store ───────────────────────────────────────────────────────────

def post_key(url: str) -> str:
    m = STATUS_ID_RE.search(url or "")
    return m.group(1) if m else (url or "").strip().lower()


def post_ids(*texts) -> set:
    found = set()
    for t in texts:
        if t:
            found.update(STATUS_ID_RE.findall(t))
    return found


def record_findings(state: dict, run_name: str, section: str, findings: list,
                    now_iso: str) -> list:
    """Merge a section's findings into state['findings']; return NEW negative
    findings (not previously stored) for second-pass targeting."""
    new_negatives = []
    for f in findings:
        if not isinstance(f, dict) or not f.get("url"):
            continue
        key = post_key(f["url"])
        if not key:
            continue
        rec = state["findings"].get(key)
        snap = {"ts": now_iso, "likes": f.get("likes"), "reposts": f.get("reposts"),
                "views": f.get("views"), "run": run_name}
        if rec is None:
            rec = {
                "handle": (f.get("handle") or "").lstrip("@"),
                "url": f["url"],
                "date": f.get("date") or "",
                "quote": (f.get("quote") or "")[:280],
                "category": f.get("category") or "other_negative",
                "severity": f.get("severity") or "low",
                "target": f.get("target") or "",
                "negative": bool(f.get("is_negative")),
                "first_seen": now_iso,
                "sections": [section],
                "engagement_history": [snap],
            }
            state["findings"][key] = rec
            if rec["negative"]:
                new_negatives.append(f)
        else:
            if section not in rec.get("sections", []):
                rec.setdefault("sections", []).append(section)
            # escalate severity if a later sweep grades it higher
            if SEVERITY_WEIGHT.get(f.get("severity"), 0) > SEVERITY_WEIGHT.get(rec.get("severity"), 0):
                rec["severity"] = f["severity"]
            rec["negative"] = rec.get("negative") or bool(f.get("is_negative"))
            hist = rec.setdefault("engagement_history", [])
            last = hist[-1] if hist else {}
            if (last.get("likes"), last.get("reposts"), last.get("views")) != \
               (snap["likes"], snap["reposts"], snap["views"]):
                hist.append(snap)
    return new_negatives


def latest_engagement(rec: dict) -> dict:
    hist = rec.get("engagement_history") or []
    return hist[-1] if hist else {}


def velocity_flags(state: dict) -> list:
    """Negative posts whose engagement accelerated between the last two snapshots."""
    flags = []
    for key, rec in state["findings"].items():
        if not rec.get("negative") or rec.get("deleted"):
            continue
        hist = rec.get("engagement_history") or []
        if len(hist) < 2:
            continue
        a, b = hist[-2], hist[-1]
        likes_a, likes_b = a.get("likes") or 0, b.get("likes") or 0
        views_a, views_b = a.get("views") or 0, b.get("views") or 0
        if (likes_b >= 5 * max(likes_a, 1) and likes_b >= 50) or (views_b - views_a >= 10000):
            flags.append((key, rec, a, b))
    return flags


def watchlist_candidates(state: dict, cfg: dict) -> list:
    """Handles with >=2 distinct negative findings, not already covered."""
    covered = watched_handles(cfg)
    counts = {}
    for rec in state["findings"].values():
        if rec.get("negative") and rec.get("handle"):
            h = rec["handle"].lower()
            if h not in covered:
                counts.setdefault(h, []).append(rec)
    out = [(h, recs) for h, recs in counts.items() if len(recs) >= 2]
    out.sort(key=lambda x: -len(x[1]))
    return out


# ── report rendering ─────────────────────────────────────────────────────────

def eng_str(f: dict) -> str:
    parts = []
    for label, k in (("L", "likes"), ("RT", "reposts"), ("V", "views")):
        v = f.get(k)
        if v is not None:
            parts.append(f"{v}{label}")
    return "/".join(parts) or "n/a"


def render_findings_table(findings: list) -> list:
    if not findings:
        return []
    lines = ["", "| sev | category | handle | engagement | date | quote | url |",
             "|---|---|---|---|---|---|---|"]
    order = sorted(findings, key=lambda f: (-SEVERITY_WEIGHT.get(f.get("severity"), 0),
                                            -(f.get("likes") or 0)))
    for f in order:
        quote = (f.get("quote") or "").replace("|", "\\|").replace("\n", " ")[:140]
        lines.append(f"| {f.get('severity', '?')} | {f.get('category', '?')} | "
                     f"@{(f.get('handle') or '?').lstrip('@')} | {eng_str(f)} | "
                     f"{(f.get('date') or '')[:10]} | {quote} | {f.get('url', '')} |")
    return lines


# ── modes: recheck + consolidate ─────────────────────────────────────────────

def pick_recheck_targets(state: dict, limit: int = 15) -> list:
    recs = [(k, r) for k, r in state["findings"].items()
            if r.get("negative") and not r.get("deleted")]
    recs.sort(key=lambda kr: (-SEVERITY_WEIGHT.get(kr[1].get("severity"), 0),
                              -(latest_engagement(kr[1]).get("likes") or 0),
                              kr[1].get("first_seen", "")))
    return recs[:limit]


def run_recheck(keys: dict, cfg: dict, state: dict, model: str, now_iso: str):
    targets = pick_recheck_targets(state)
    if not targets:
        return None, [], {}
    urls = "\n".join(f"- {r['url']}" for _, r in targets)
    body = build_body(RECHECK_PROMPT.replace("__URLS__", urls),
                      media_params(cfg), model, "x_monitor_recheck", RECHECK_SCHEMA)
    _, result = xai_query(keys["XAI_API_KEY"], "recheck", body)
    if not result["ok"]:
        return result, [], {}
    deltas = []
    for p in result["payload"].get("posts", []):
        key = post_key(p.get("url", ""))
        rec = state["findings"].get(key)
        if not rec:
            continue
        if p.get("deleted"):
            rec["deleted"] = True
            deltas.append((rec, None, {"deleted": True}))
            continue
        prev = latest_engagement(rec)
        snap = {"ts": now_iso, "likes": p.get("likes"), "reposts": p.get("reposts"),
                "views": p.get("views"), "run": "recheck"}
        rec.setdefault("engagement_history", []).append(snap)
        deltas.append((rec, prev, snap))
    return result, deltas, result.get("usage", {})


def run_consolidate(state: dict, days: int, ts: str) -> str:
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    for rec in state["findings"].values():
        if not rec.get("negative"):
            continue
        when = (rec.get("date") or rec.get("first_seen") or "")[:10]
        if when and when < cutoff:
            continue
        rows.append(rec)

    def tier_of(r):
        e = latest_engagement(r)
        likes, views = e.get("likes") or 0, e.get("views") or 0
        if likes >= 100 or views >= 10000 or (r.get("severity") == "high" and likes >= 20):
            return 1
        return 2

    lines = [f"# X Monitor — consolidated negative collection ({days}d) — {ts}Z", ""]
    for tier in (1, 2):
        members = [r for r in rows if tier_of(r) == tier]
        members.sort(key=lambda r: -(latest_engagement(r).get("likes") or 0))
        lines.append(f"## Tier {tier} — {'real engagement' if tier == 1 else 'low-traction'} "
                     f"({len(members)})")
        by_cat = {}
        for r in members:
            by_cat.setdefault(r.get("category", "other_negative"), []).append(r)
        for cat in sorted(by_cat):
            lines.append(f"\n### {cat}")
            for r in by_cat[cat]:
                e = latest_engagement(r)
                deleted = " **[DELETED]**" if r.get("deleted") else ""
                lines.append(f"- **@{r['handle']}** ({(r.get('date') or '?')[:10]}, "
                             f"{eng_str(e)}, sev {r.get('severity')}){deleted}: "
                             f"\"{r.get('quote', '')[:200]}\" {r.get('url')}")
        lines.append("")
    path = os.path.join(REPORT_DIR, f"{ts}-x-monitor-consolidated-{days}d.md")
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="On-demand X perception/adversarial monitor")
    ap.add_argument("--mode", default="full",
                    choices=["full", "subjects", "adversarial", "watchlist", "event",
                             "recheck", "consolidate"])
    ap.add_argument("--subject", help="limit subjects mode to one configured subject id")
    ap.add_argument("--query", help="event text for --mode event")
    ap.add_argument("--from-date", dest="from_date")
    ap.add_argument("--to-date", dest="to_date")
    ap.add_argument("--days", type=int, default=30, help="window for --mode consolidate")
    ap.add_argument("--no-web", action="store_true", help="skip flat web-index sweeps")
    ap.add_argument("--no-second-pass", action="store_true",
                    help="skip copy-chain/author-expansion follow-ups")
    ap.add_argument("--model", help="override config model for this run")
    ap.add_argument("--batch", action="store_true",
                    help="EXPERIMENTAL: run xAI jobs via Batch API (~half token cost, async poll)")
    ap.add_argument("--batch-timeout", type=int, default=7200)
    ap.add_argument("--smoke", action="store_true",
                    help="cheap end-to-end validation: critics watchlist + 1 web query/provider")
    ap.add_argument("--no-preflight", action="store_true",
                    help="skip the pinned-model liveness probe (probe-before-panel)")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args()
    if args.mode == "event" and not args.query and not args.smoke:
        ap.error("--mode event requires --query")
    if args.smoke and args.batch:
        ap.error("--smoke validates the sync path; drop --batch")

    cfg = load_config(args.config)
    model = args.model or cfg.get("model", "grok-4.3")
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = load_state()

    # consolidate is local-only: no API keys, no window
    if args.mode == "consolidate":
        path = run_consolidate(state, args.days, ts)
        neg = sum(1 for r in state["findings"].values() if r.get("negative"))
        print(f"Consolidated {neg} tracked negative findings (window {args.days}d)")
        print(f"Report: {path}")
        return

    today = datetime.date.today()
    lookback = 7 if args.smoke else cfg.get("default_lookback_days", 30)
    window = {
        "from_date": args.from_date or (today - datetime.timedelta(days=lookback)).isoformat(),
        "to_date": args.to_date or today.isoformat(),
    }

    keys = {n: resolve_key(n) for n in ("XAI_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY")}
    if not keys["XAI_API_KEY"]:
        print("FATAL: XAI_API_KEY not found in env or Keychain", file=sys.stderr)
        sys.exit(1)

    # Probe-before-panel: verify the pinned Grok model still resolves and is not
    # silently redirected to a different model (the May-15-2026 rebill shape) or
    # served off a retired endpoint. Warn-and-continue (a redirected run still
    # produces data; the operator needs to KNOW the pin drifted). Reuses the
    # validated gather-vendor probe. Skip with --no-preflight.
    if not args.no_preflight:
        probe = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "skills", "gather-vendor", "scripts", "probe_models.py")
        probe = os.path.normpath(probe)
        if os.path.exists(probe):
            try:
                pr = subprocess.run([sys.executable, probe, "xai", model],
                                    capture_output=True, text=True, timeout=60)
                last = (pr.stdout + pr.stderr).strip().splitlines()
                last = last[-1] if last else f"probe exit {pr.returncode}"
                if pr.returncode == 1:      # retirement/redirect — the pin actually drifted
                    print(f"WARNING: pinned model '{model}' looks RETIRED/REDIRECTED: {last}",
                          file=sys.stderr)
                    print("  x-monitor will run, but verify the pin (run /gather-vendor grok).",
                          file=sys.stderr)
                elif pr.returncode != 0:    # transient / auth-infra — not a pin problem
                    print(f"WARNING: preflight inconclusive (transient/auth): {last}; continuing.",
                          file=sys.stderr)
            except Exception as e:  # noqa: BLE001 — preflight must not kill the run
                print(f"WARNING: preflight probe error ({type(e).__name__}); continuing.",
                      file=sys.stderr)
        else:
            print(f"WARNING: preflight skipped — gather-vendor probe not found at {probe}.",
                  file=sys.stderr)

    # ── recheck mode: one query, engagement deltas on tracked negatives ──
    if args.mode == "recheck":
        result, deltas, usage = run_recheck(keys, cfg, state, model, now_iso)
        if result is None:
            print("recheck: no tracked negative findings yet")
            return
        if not result["ok"]:
            print(f"recheck FAILED: {result['error'][:300]}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(REPORT_DIR, exist_ok=True)
        report_path = os.path.join(REPORT_DIR, f"{ts}-x-monitor-recheck.md")
        lines = [f"# X Monitor — {ts}Z (mode: recheck)", "",
                 f"Rechecked: {len(deltas)} tracked negative posts | model: {model} | "
                 f"cost: ${usage.get('cost_usd', 0):.3f}", ""]
        accel = []
        for rec, prev, snap in deltas:
            if snap.get("deleted"):
                lines.append(f"- **DELETED**: @{rec['handle']} \"{rec.get('quote', '')[:80]}\" {rec['url']}")
                continue
            dl = (snap.get("likes") or 0) - ((prev or {}).get("likes") or 0)
            dv = (snap.get("views") or 0) - ((prev or {}).get("views") or 0)
            lines.append(f"- @{rec['handle']}: {eng_str(prev or {})} -> {eng_str(snap)} "
                         f"(Δlikes {dl:+d}, Δviews {dv:+d}) {rec['url']}")
            if ((snap.get("likes") or 0) >= 5 * max((prev or {}).get("likes") or 0, 1)
                    and (snap.get("likes") or 0) >= 50) or dv >= 10000:
                accel.append(rec)
        if accel:
            lines += ["", "## ⚠ ACCELERATING", ""]
            lines += [f"- @{r['handle']} \"{r.get('quote', '')[:120]}\" {r['url']}" for r in accel]
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        save_state(state)
        print(f"Report: {report_path}")
        print(f"Rechecked {len(deltas)}; accelerating: {len(accel)}; "
              f"cost ${usage.get('cost_usd', 0):.3f}")
        return

    # ── sweep modes ──
    if args.smoke:
        crit = cfg["watchlists"]["critics"]
        jobs = [("watchlist:critics(smoke)",
                 WATCHLIST_TMPL.replace("__HANDLES__", ", ".join("@" + h for h in crit["handles"][:20]))
                               .replace("__TOPICS__", crit["topics"]),
                 {**window, **media_params(cfg), "allowed_x_handles": crit["handles"][:20]})]
    else:
        jobs = build_xai_jobs(cfg, args.mode, window, args)

    print(f"x-monitor mode={args.mode}{' (smoke)' if args.smoke else ''} "
          f"window={window['from_date']}..{window['to_date']} model={model} "
          f"xai_queries={len(jobs)} web={'off' if args.no_web else 'on'} "
          f"batch={'on' if args.batch else 'off'}", flush=True)

    xai_results = run_xai_jobs(keys["XAI_API_KEY"], jobs, model, args.batch, args.batch_timeout)

    # merge findings; collect NEW negatives for second pass
    new_negatives = []
    run_tag = f"{ts}-{args.mode}"
    for name, r in xai_results.items():
        if r.get("ok"):
            new_negatives.extend(
                record_findings(state, run_tag, name, r["payload"].get("findings", []), now_iso))

    # ── second pass: copy-chain + author-expansion (sync, small) ──
    if new_negatives and not args.no_second_pass and not args.smoke:
        sp_jobs = second_pass_jobs(cfg, window, new_negatives)
        if sp_jobs:
            print(f"  second pass: {len(sp_jobs)} follow-up "
                  f"quer{'y' if len(sp_jobs) == 1 else 'ies'} "
                  f"({len(new_negatives)} new negative findings)", flush=True)
            sp_results = run_xai_jobs(keys["XAI_API_KEY"], sp_jobs, model, False, 0)
            for name, r in sp_results.items():
                xai_results[name] = r
                if r.get("ok"):
                    record_findings(state, run_tag, name, r["payload"].get("findings", []), now_iso)

    web = {"tavily": [], "firecrawl": [], "errors": []}
    if not args.no_web:
        web = web_sweeps(cfg, keys, args.smoke,
                         args.query if args.mode == "event" else None)
        for p in ("tavily", "firecrawl"):
            print(f"  [web:{p}] {sum(len(b['hits']) for b in web[p])} hits "
                  f"across {len(web[p])} queries", flush=True)
        for err in web["errors"]:
            print(f"  [web:ERROR] {err}", flush=True)

    # ── delta against seen-state ──
    seen = state["seen"]
    new_by_section, all_current = {}, set()
    for name, r in xai_results.items():
        ids = set()
        if r.get("ok"):
            ids = post_ids(r["payload"].get("narrative"),
                           "\n".join(f.get("url", "") for f in r["payload"].get("findings", [])),
                           "\n".join(r.get("cited", [])),
                           "\n".join(r.get("encountered", [])))
        all_current |= ids
        new_by_section[name] = sorted(i for i in ids if i not in seen)
    web_ids = set()
    for p in ("tavily", "firecrawl"):
        for batch in web[p]:
            web_ids |= post_ids("\n".join(u for u, _ in batch["hits"]))
    all_current |= web_ids
    new_by_section["web-sweep"] = sorted(i for i in web_ids if i not in seen)
    total_new = sum(len(v) for v in new_by_section.values())
    total_cost = sum(r.get("usage", {}).get("cost_usd", 0) for r in xai_results.values() if r.get("ok"))
    total_tools = sum(r.get("usage", {}).get("tools_used", 0) for r in xai_results.values() if r.get("ok"))

    # ── report (written BEFORE state update — see INTERRUPTION note) ──
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"{ts}-x-monitor-{args.mode}{'-smoke' if args.smoke else ''}.md")
    lines = [
        f"# X Monitor — {ts}Z (mode: {args.mode}{', smoke' if args.smoke else ''})",
        "",
        f"Window: {window['from_date']} → {window['to_date']} | model: {model} | "
        f"new posts: {total_new} | previously seen: {len(all_current) - total_new} | "
        f"web sweeps: {'off' if args.no_web else 'on'} | "
        f"**run cost: ${total_cost:.3f}** ({total_tools} server-side tool calls)",
        "",
    ]
    all_actionables = []
    for name, r in xai_results.items():
        lines += [f"## {name}", ""]
        if r.get("ok"):
            u = r.get("usage", {})
            fallback = " (STRUCTURED PARSE FELL BACK TO PROSE)" if u.get("parse_fallback") else ""
            lines.append(f"_cost ${u.get('cost_usd', 0):.3f} | {u.get('tools_used', 0)} tool calls{fallback}_")
            lines += ["", r["payload"].get("narrative", ""), ""]
            findings = r["payload"].get("findings", [])
            neg = [f for f in findings if f.get("is_negative")]
            if findings:
                lines.append(f"**Findings ({len(findings)}, {len(neg)} negative):**")
                lines += render_findings_table(findings)
                lines.append("")
            for a in r["payload"].get("actionable_items", []):
                all_actionables.append(f"[{name}] {a}")
            eq = r["payload"].get("empty_queries", [])
            if eq:
                lines.append(f"**Empty queries ({len(eq)}):** " + " · ".join(f"`{q}`" for q in eq))
            news = new_by_section.get(name, [])
            lines.append(f"**NEW post IDs this run ({len(news)}):** " +
                         (", ".join(f"[{i}](https://x.com/i/status/{i})" for i in news) or "none"))
            lines.append(f"**Cited URLs:** {len(r.get('cited', []))} | "
                         f"encountered sources: {len(r.get('encountered', []))}")
        else:
            lines.append(f"FAILED: {r['error']}")
        lines.append("")

    if all_actionables:
        lines += ["## ACTIONABLE ITEMS", ""]
        lines += [f"- {a}" for a in all_actionables] + [""]

    vflags = velocity_flags(state)
    if vflags:
        lines += ["## ⚠ ENGAGEMENT VELOCITY", ""]
        for key, rec, a, b in vflags:
            lines.append(f"- @{rec['handle']}: {eng_str(a)} -> {eng_str(b)} "
                         f"\"{rec.get('quote', '')[:100]}\" {rec['url']}")
        lines.append("")

    candidates = watchlist_candidates(state, cfg)
    if candidates:
        lines += ["## WATCHLIST CANDIDATES (repeat negative authors, not yet watched)", ""]
        for h, recs in candidates[:10]:
            cats = sorted({r.get("category", "?") for r in recs})
            lines.append(f"- **@{h}** — {len(recs)} negative finds ({', '.join(cats)})")
        lines.append("")

    if not args.no_web:
        lines += ["## Web-index sweep (flat ranking — bias control)", ""]
        for p in ("tavily", "firecrawl"):
            for batch in web[p]:
                lines.append(f"**{p}** — `{batch['query']}`")
                for url, title in batch["hits"]:
                    ids = post_ids(url)
                    tag = " **NEW**" if ids and next(iter(ids)) in new_by_section["web-sweep"] else ""
                    lines.append(f"- [{title or url}]({url}){tag}")
                if batch.get("non_x"):
                    lines.append(f"- _(+{batch['non_x']} non-X results suppressed)_")
                lines.append("")
        if web["errors"]:
            lines += ["**Provider errors (fail-soft):**"] + [f"- {e}" for e in web["errors"]] + [""]
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    for pid in all_current:
        if pid not in seen:
            seen[pid] = {"first_seen": now_iso, "run": os.path.basename(report_path)}
    save_state(state)

    print(f"\nReport: {report_path}")
    print(f"NEW posts: {total_new} | total tracked: {len(seen)} | "
          f"tracked findings: {len(state['findings'])} | run cost: ${total_cost:.3f}")
    for name, ids in new_by_section.items():
        if ids:
            print(f"  {name}: {len(ids)} new")
    if all_actionables:
        print(f"ACTIONABLE: {len(all_actionables)} item(s) — see report")
    if vflags:
        print(f"VELOCITY: {len(vflags)} accelerating post(s) — see report")


if __name__ == "__main__":
    main()
