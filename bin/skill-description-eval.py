#!/usr/bin/env python3
"""Trigger-rate eval for the skill descriptions that route this harness.

Skills are routed purely by the text Claude Code shows the model for each one:
`description` + `when_to_use`, cut at 1,536 characters, for every skill without
`disable-model-invocation: true`. Nothing measured whether those texts actually
fire for the requests their skills exist for, or which skill steals which. This
script produces that evidence in three deterministic-shaped steps:

  corpus  For each model-visible skill, ask a generator model for 3 realistic
          user requests written FROM THE SKILL BODY WITH THE FRONTMATTER
          (description and when_to_use) REMOVED, so positives are grounded in
          what the skill does rather than paraphrasing its own routing text.
          Adds 30 hand-written generic requests that should route to no skill.
          -> skills/_shared/description-eval/corpus.json

  route   Send every request to the routing model with ONE cached system
          prompt that lists all model-visible skills as `name: listing` (the
          table the runtime effectively uses) and constrain the answer to one
          skill name or "none" with a JSON-schema enum. Estimates cost first
          and refuses to run over --max-cost; stops early if actual spend
          crosses it.  -> skills/_shared/description-eval/results-<date>.json

  report  Per-skill recall, confusion pairs (which skill captured whose
          requests), false-fire rate on the generic requests, overall table.
          Written back into the results file and to
          skills/_shared/description-eval/README.md.

Run with the Anthropic SDK supplied by uv (nothing is installed into the venv):

  export ANTHROPIC_API_KEY="$(security find-generic-password -s ANTHROPIC_API_KEY -w)" \\
    && uv run --with anthropic --with pyyaml python3 bin/skill-description-eval.py corpus
  ... route
  ... report

The key is read by the SDK from the environment and is never printed or written.
Deterministic tests: scripts/test_skill_description_eval.py (fake client, no network).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"
EVAL_DIR = SKILLS_DIR / "_shared" / "description-eval"
CORPUS_PATH = EVAL_DIR / "corpus.json"
README_PATH = EVAL_DIR / "README.md"

CORPUS_MODEL = "claude-sonnet-5"      # generator: cheap, and not the model under test
ROUTE_MODEL = "claude-fable-5-1"      # the model the owner runs
POSITIVES_PER_SKILL = 3
LISTING_CHARACTER_CAP = 1536          # Claude Code truncates description + when_to_use here
NONE = "none"
DEFAULT_MAX_COST_USD = 10.0
OUTPUT_TOKENS_ASSUMED = 500           # per routing request incl. thinking, conservative at effort=low
CORPUS_OUTPUT_TOKENS_ASSUMED = 1500   # per generation request incl. thinking

# USD per 1M tokens, Anthropic first-party rates (claude-api skill table, cached 2026-06-24).
# Cache write = 1.25x input (5-minute TTL); cache read = 0.1x input, except Fable 5.1 at $0.25.
PRICING = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
    "claude-fable-5-1": {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 0.25},
    "claude-fable-5": {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 1.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---[ \t]*\n?", re.DOTALL)

# Thirty everyday requests that no skill in this harness covers. Labelled "none":
# a router that picks a skill for any of these is over-firing.
GENERIC_REQUESTS = [
    "Rename the variable `cnt` to `count` everywhere in utils.py.",
    "Convert this callback-style function to async/await.",
    "What's the difference between a Python list and a tuple?",
    "Add a --verbose flag to the CLI that prints each file as it is processed.",
    "Explain what this regular expression matches: ^\\d{3}-\\d{4}$",
    "Sort the imports in this module alphabetically.",
    "Write a SQL query that returns the ten customers with the highest total order value.",
    "Generate a .gitignore for a Node.js project.",
    "What is the time complexity of this nested loop?",
    "Translate this bash script to PowerShell.",
    "Pretty-print this JSON blob so it is readable.",
    "Add type hints to the functions in models.py.",
    "Add a Makefile target called lint that runs ruff.",
    "Explain the difference between TCP and UDP in two paragraphs.",
    "Bump the version in package.json from 2.2.1 to 2.3.0.",
    "Convert this CSV snippet into a markdown table.",
    "Write a docstring for the DateRange class.",
    "What does HTTP status 422 mean?",
    "Remove the unused imports at the top of main.py.",
    "Show me how to define argparse subcommands.",
    "Change the default port in config.yaml from 8000 to 8080.",
    "Write a regex that matches US phone numbers with an optional area code in parentheses.",
    "Add a null check before we dereference user.profile in the request handler.",
    "Convert the tabs in these files to four spaces.",
    "Explain what a Python context manager is, with a short example.",
    "Write a bash one-liner that counts lines of code per file extension.",
    "Turn this synchronous file read into a streaming read so it works on large files.",
    "Draft a short README section describing how to install the package with pip.",
    "How do I center a div horizontally and vertically with CSS flexbox?",
    "Write a unit test for the slugify helper that covers unicode input.",
]

ROUTER_INSTRUCTIONS = """\
You are the skill router inside Claude Code, an AI coding assistant. The assistant can invoke \
the skills listed below; each line is `name: description`, exactly the text the runtime shows \
the model.

Given the user's request, answer with the single skill the assistant should invoke for it, or \
"none" when no listed skill applies. Ordinary coding, writing, and explanation requests that no \
skill specifically covers are "none". Judge only from the descriptions below.

Skills:
"""

CORPUS_INSTRUCTIONS = (
    "You write realistic user requests for evaluating how an AI coding assistant routes "
    "requests to its internal procedures."
)

CORPUS_SCHEMA = {
    "type": "object",
    "properties": {"requests": {"type": "array", "items": {"type": "string"}}},
    "required": ["requests"],
    "additionalProperties": False,
}


class BudgetExceeded(RuntimeError):
    """Raised before any paid request when the estimate is over --max-cost."""


# --------------------------------------------------------------------------- skills

def frontmatter_and_body(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.search(text)
    if not match:
        return {}, text
    value = yaml.safe_load(match.group(1)) or {}
    return (value if isinstance(value, dict) else {}), text[match.end():]


def listing_text(description: str, when_to_use: str) -> str:
    """What the model sees for one skill: description + when_to_use, capped."""
    combined = " ".join(part for part in (description, when_to_use) if part)
    return combined[:LISTING_CHARACTER_CAP]


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[dict]:
    skills = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        if skill_md.parent.name == "_shared":
            continue
        fm, body = frontmatter_and_body(skill_md.read_text(encoding="utf-8"))
        description = " ".join(str(fm.get("description") or "").split())
        when_to_use = " ".join(str(fm.get("when_to_use") or "").split())
        skills.append({
            "name": skill_md.parent.name,
            "description": description,
            "when_to_use": when_to_use,
            "listing": listing_text(description, when_to_use),
            "body": body,
            "model_visible": fm.get("disable-model-invocation") is not True,
        })
    return skills


def visible_skills(skills: list[dict]) -> list[dict]:
    return sorted((s for s in skills if s["model_visible"]), key=lambda s: s["name"])


def routing_system_prompt(skills: list[dict]) -> str:
    lines = [f"- {s['name']}: {s['listing']}" for s in visible_skills(skills)]
    return ROUTER_INSTRUCTIONS + "\n".join(lines) + "\n"


def answer_schema(skill_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"skill": {"type": "string", "enum": [*skill_names, NONE]}},
        "required": ["skill"],
        "additionalProperties": False,
    }


# --------------------------------------------------------------------------- SDK glue

def make_client():
    """Real Anthropic client. Imported lazily so tests run without the SDK."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("error: no Anthropic credentials in the environment (ANTHROPIC_API_KEY or "
              "ANTHROPIC_AUTH_TOKEN); nothing was sent", file=sys.stderr)
        raise SystemExit(2)
    import anthropic
    return anthropic.Anthropic(max_retries=5, timeout=180.0)


def usage_of(response) -> dict:
    usage = getattr(response, "usage", None)
    return {
        key: int(getattr(usage, key, 0) or 0)
        for key in ("input_tokens", "output_tokens",
                    "cache_creation_input_tokens", "cache_read_input_tokens")
    }


def usage_cost(usage: dict, model: str) -> float:
    rates = PRICING[model]
    return (usage.get("input_tokens", 0) * rates["input"]
            + usage.get("output_tokens", 0) * rates["output"]
            + usage.get("cache_creation_input_tokens", 0) * rates["cache_write"]
            + usage.get("cache_read_input_tokens", 0) * rates["cache_read"]) / 1e6


def add_usage(total: dict, usage: dict) -> None:
    for key, value in usage.items():
        total[key] = total.get(key, 0) + value
    total["requests"] = total.get("requests", 0) + 1


def first_text(response) -> str:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- corpus

def corpus_user_prompt(body: str, n: int) -> str:
    return (
        "Below is the body of an internal procedure (\"skill\") that an AI coding assistant "
        "can run. Its title and summary have been removed on purpose.\n\n"
        f"Write {n} distinct requests that a user might type to the assistant in a situation "
        "where THIS procedure is the right one to run.\n\n"
        "Rules:\n"
        "- Write in the user's voice, 1-3 sentences each, as a real request (a task, question, "
        "or situation), not a description of the procedure.\n"
        "- Ground each request in a concrete situation the procedure is built for, and vary "
        "them: one short and direct; one with situational detail (what happened, what they "
        "have, what they want); one that states the need without using the procedure's own "
        "vocabulary.\n"
        "- Do not name the procedure, its slash command, or any file path from the document; "
        "do not copy phrases verbatim from it.\n"
        "- Do not mention that a procedure or skill exists.\n\n"
        'Return JSON: {"requests": ["...", "...", "..."]}\n\n'
        f"<procedure>\n{body}\n</procedure>\n"
    )


def estimate_corpus_cost(skills: list[dict], model: str,
                         output_tokens: int = CORPUS_OUTPUT_TOKENS_ASSUMED) -> dict:
    rates = PRICING[model]
    visible = visible_skills(skills)
    input_tokens = sum(len(corpus_user_prompt(s["body"], POSITIVES_PER_SKILL)) // 4 + 100 for s in visible)
    input_usd = input_tokens * rates["input"] / 1e6
    output_usd = len(visible) * output_tokens * rates["output"] / 1e6
    return {"requests": len(visible), "input_tokens": input_tokens, "output_tokens_assumed": output_tokens,
            "input_usd": input_usd, "output_usd": output_usd, "total_usd": input_usd + output_usd}


def build_corpus(skills: list[dict], client, model: str = CORPUS_MODEL,
                 positives: int = POSITIVES_PER_SKILL, generic: list[str] = GENERIC_REQUESTS,
                 effort: str = "medium", concurrency: int = 4) -> dict:
    items, errors, usage_total = [], {}, {}
    visible = visible_skills(skills)

    def generate(skill):
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=CORPUS_INSTRUCTIONS,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": CORPUS_SCHEMA}},
            messages=[{"role": "user", "content": corpus_user_prompt(skill["body"], positives)}],
        )
        log(f"  generated {skill['name']} (stop={getattr(response, 'stop_reason', None)}, "
            f"output_tokens={usage_of(response)['output_tokens']})")
        return response

    # Sequential generation measured ~11 s per skill (Sonnet 5, medium effort); a
    # small pool keeps the run under a few minutes. map() preserves skill order.
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        responses = list(pool.map(generate, visible))

    for skill, response in zip(visible, responses):
        add_usage(usage_total, usage_of(response))
        stop = getattr(response, "stop_reason", None)
        if stop != "end_turn":
            errors[skill["name"]] = f"stop_reason={stop}"
            continue
        try:
            requests = json.loads(first_text(response)).get("requests", [])
        except (json.JSONDecodeError, AttributeError) as exc:
            errors[skill["name"]] = f"unparseable answer: {exc}"
            continue
        requests = [r.strip() for r in requests if isinstance(r, str) and r.strip()][:positives]
        if len(requests) < positives:
            errors[skill["name"]] = f"only {len(requests)} request(s) generated"
        for n, request in enumerate(requests, 1):
            items.append({"id": f"{skill['name']}-{n}", "request": request,
                          "expected": skill["name"], "kind": "positive"})
    for n, request in enumerate(generic, 1):
        items.append({"id": f"generic-{n:02d}", "request": request, "expected": NONE, "kind": "negative"})
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "effort": effort,
            "skills": len(visible),
            "positives_per_skill": positives,
            "negatives": len(generic),
            "method": ("positives generated from each SKILL.md body with the frontmatter "
                       "(description, when_to_use) removed; generator told not to name the skill, "
                       "its slash command, or copy phrases verbatim; negatives hand-written"),
            "usage": usage_total,
            "cost_usd": usage_cost(usage_total, model),
            "generation_errors": errors,
        },
        "items": items,
    }


# --------------------------------------------------------------------------- route

def estimate_route_cost(system_tokens: int, n_items: int, model: str,
                        request_tokens: int = 60, output_tokens: int = OUTPUT_TOKENS_ASSUMED) -> dict:
    rates = PRICING[model]
    cache_write_usd = 2 * system_tokens * rates["cache_write"] / 1e6      # warm + one TTL lapse
    cache_read_usd = n_items * system_tokens * rates["cache_read"] / 1e6
    input_usd = n_items * request_tokens * rates["input"] / 1e6
    output_usd = n_items * output_tokens * rates["output"] / 1e6
    return {
        "system_tokens": system_tokens, "requests": n_items, "request_tokens_assumed": request_tokens,
        "output_tokens_assumed": output_tokens,
        "cache_write_usd": cache_write_usd, "cache_read_usd": cache_read_usd,
        "input_usd": input_usd, "output_usd": output_usd,
        "total_usd": cache_write_usd + cache_read_usd + input_usd + output_usd,
    }


def count_system_tokens(client, model: str, system_blocks: list[dict]) -> int:
    try:
        counted = client.messages.count_tokens(
            model=model, system=system_blocks, messages=[{"role": "user", "content": "x"}])
        return int(counted.input_tokens)
    except Exception as exc:  # noqa: BLE001 -- estimate only; fall back to a chars/4 proxy
        log(f"  count_tokens unavailable ({type(exc).__name__}); using chars/4 proxy")
        return sum(len(block["text"]) for block in system_blocks) // 4


def route_one(client, model: str, effort: str, system_blocks: list[dict], schema: dict,
              skill_names: list[str], item: dict) -> dict:
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system_blocks,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": item["request"]}],
    )
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        answer = "refusal"
    elif stop != "end_turn":
        answer = f"error:{stop}"
    else:
        try:
            answer = str(json.loads(first_text(response)).get("skill", ""))
        except (json.JSONDecodeError, AttributeError):
            answer = "error:parse"
        if answer not in skill_names and answer != NONE:
            answer = f"error:unknown:{answer}"
    details = getattr(response, "stop_details", None)   # populated only when stop_reason is refusal
    return {**item, "answer": answer, "stop_reason": stop,
            "stop_details": ({"category": getattr(details, "category", None),
                              "explanation": getattr(details, "explanation", None)} if details else None),
            "model": getattr(response, "model", None), "usage": usage_of(response)}


def route_corpus(corpus: dict, skills: list[dict], client, model: str = ROUTE_MODEL,
                 effort: str = "low", concurrency: int = 4, limit: int | None = None,
                 max_cost_usd: float = DEFAULT_MAX_COST_USD,
                 output_tokens_assumed: int = OUTPUT_TOKENS_ASSUMED) -> dict:
    visible = visible_skills(skills)
    names = [s["name"] for s in visible]
    system_text = routing_system_prompt(visible)
    system_blocks = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
    schema = answer_schema(names)
    items = sorted(corpus["items"], key=lambda i: i["id"])
    if limit:
        items = items[:limit]

    system_tokens = count_system_tokens(client, model, system_blocks)
    request_tokens = int(statistics.mean(len(i["request"]) for i in items) // 4 + 8) if items else 8
    estimate = estimate_route_cost(system_tokens, len(items), model, request_tokens, output_tokens_assumed)
    log(f"estimate: {len(items)} requests, system {system_tokens} tokens (cached), "
        f"~{output_tokens_assumed} output tokens each -> ${estimate['total_usd']:.2f} "
        f"(cache write {estimate['cache_write_usd']:.2f} + reads {estimate['cache_read_usd']:.2f} "
        f"+ input {estimate['input_usd']:.2f} + output {estimate['output_usd']:.2f})")
    if estimate["total_usd"] > max_cost_usd:
        raise BudgetExceeded(f"estimated ${estimate['total_usd']:.2f} exceeds budget ${max_cost_usd:.2f}; "
                             f"nothing sent")

    started = datetime.now(timezone.utc)
    routes, usage_total, exceeded = [], {}, False

    def run(item):
        return route_one(client, model, effort, system_blocks, schema, names, item)

    def absorb(done):
        nonlocal exceeded
        for result in done:
            routes.append(result)
            add_usage(usage_total, result["usage"])
        if usage_cost(usage_total, model) > max_cost_usd:
            exceeded = True

    if items:
        absorb([run(items[0])])              # warm the cache before fanning out
        log(f"  1/{len(items)} routed; cache_creation={routes[0]['usage']['cache_creation_input_tokens']} "
            f"cache_read={routes[0]['usage']['cache_read_input_tokens']} "
            f"output={routes[0]['usage']['output_tokens']}")
    rest = items[1:]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for start in range(0, len(rest), max(1, concurrency)):
            if exceeded:
                log("  actual spend crossed the budget; stopping early")
                break
            absorb(list(pool.map(run, rest[start:start + max(1, concurrency)])))
            log(f"  {len(routes)}/{len(items)} routed, ${usage_cost(usage_total, model):.2f} so far")
    routes.sort(key=lambda r: r["id"])
    finished = datetime.now(timezone.utc)
    return {
        "meta": {
            "model": model,
            "effort": effort,
            "date": started.date().isoformat(),
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "skills": names,
            "system_prompt_sha256": hashlib.sha256(system_text.encode("utf-8")).hexdigest(),
            "system_tokens": system_tokens,
            "estimate": estimate,
            "budget_usd": max_cost_usd,
            "budget_exceeded": exceeded,
            "limit": limit,
            "usage": usage_total,
            "cost_usd": usage_cost(usage_total, model),
            "corpus_meta": corpus.get("meta", {}),
        },
        "routes": routes,
    }


# --------------------------------------------------------------------------- report

def compute_report(results: dict) -> dict:
    routes = results["routes"]
    positives = [r for r in routes if r["kind"] == "positive"]
    negatives = [r for r in routes if r["kind"] == "negative"]
    skill_names = sorted(set(results["meta"].get("skills") or []) | {r["expected"] for r in positives})

    per_skill = {}
    for name in skill_names:
        mine = [r for r in positives if r["expected"] == name]
        hits = sum(1 for r in mine if r["answer"] == name)
        per_skill[name] = {
            "positives": len(mine),
            "hits": hits,
            "recall": (hits / len(mine)) if mine else None,
            "to_none": sum(1 for r in mine if r["answer"] == NONE),
            "refused": sum(1 for r in mine if r["answer"] == "refusal"),
            "captured": sum(1 for r in routes if r["answer"] == name and r["expected"] != name),
        }

    confusion = Counter((r["expected"], r["answer"]) for r in positives
                        if r["answer"] in skill_names and r["answer"] != r["expected"])
    confusion_rows = [{"expected": e, "got": g, "count": c} for (e, g), c in confusion.items()]
    confusion_rows.sort(key=lambda row: (-row["count"], row["expected"], row["got"]))

    fired = [r for r in negatives if r["answer"] in skill_names]
    false_fire = {
        "negatives": len(negatives),
        "fired": len(fired),
        "rate": (len(fired) / len(negatives)) if negatives else 0.0,
        "fired_items": [{"id": r["id"], "request": r["request"], "got": r["answer"]} for r in fired],
    }

    misses = [
        {"id": r["id"], "expected": r["expected"], "got": r["answer"], "request": r["request"],
         "category": (r.get("stop_details") or {}).get("category")}
        for r in sorted(positives, key=lambda r: r["id"]) if r["answer"] != r["expected"]
    ]

    measured = [v["recall"] for v in per_skill.values() if v["recall"] is not None]
    hits_total = sum(v["hits"] for v in per_skill.values())
    overall = {
        "skills": len(skill_names),
        "positives": len(positives),
        "hits": hits_total,
        "micro_recall": (hits_total / len(positives)) if positives else 0.0,
        "macro_recall": statistics.mean(measured) if measured else 0.0,
        "negatives": len(negatives),
        "false_fire_rate": false_fire["rate"],
        "refusals": sum(1 for r in routes if r["answer"] == "refusal"),
        "errors": sum(1 for r in routes if str(r["answer"]).startswith("error:")),
        "skills_never_hit": sorted(n for n, v in per_skill.items() if v["recall"] == 0.0),
        "skills_without_positives": sorted(n for n, v in per_skill.items() if v["recall"] is None),
        "skills_capturing_foreign": sorted(
            ((n, v["captured"]) for n, v in per_skill.items() if v["captured"] > 0),
            key=lambda pair: (-pair[1], pair[0])),
    }
    return {"per_skill": per_skill, "confusion": confusion_rows, "false_fire": false_fire,
            "misses": misses, "overall": overall}


def _fmt_recall(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render_readme(report: dict, meta: dict, results_name: str) -> str:
    per, overall, ff = report["per_skill"], report["overall"], report["false_fire"]
    ranked = sorted(per.items(), key=lambda kv: (kv[1]["recall"] if kv[1]["recall"] is not None else -1, kv[0]))
    corpus_meta = meta.get("corpus_meta", {})
    lines = [
        "# Skill description trigger-rate eval",
        "",
        (f"Generated by `bin/skill-description-eval.py report` from `{results_name}`. Do not hand-edit; "
        "re-run the eval to refresh."),
        "",
        "## Method",
        "",
        (f"- Routing model: `{meta.get('model')}` at effort `{meta.get('effort')}`, run {meta.get('date')}. "
        "One request per corpus item, no repeats."),
        ("- Routing table: one cached system prompt listing every model-visible skill as "
        "`name: description + when_to_use` cut at 1,536 characters (the runtime listing contract in "
        "`scripts/validate-skills.py` A2). The answer is constrained to one skill name or `none`."),
        (f"- Corpus: {corpus_meta.get('positives_per_skill', '?')} positives per skill generated by "
        f"`{corpus_meta.get('model', '?')}` from the SKILL.md body with the frontmatter removed, plus "
        f"{corpus_meta.get('negatives', overall['negatives'])} hand-written generic requests labelled `none`."),
        (f"- Cost of the routing run: ${meta.get('cost_usd', 0.0):.2f} "
        f"({meta.get('usage', {}).get('requests', 0)} requests; corpus generation "
        f"${corpus_meta.get('cost_usd', 0.0):.2f})."),
        ("- A positive that routes to `none` is a miss the description caused; one that routes to another "
        "skill is a collision. A negative that routes anywhere is a false fire."),
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Model-visible skills | {overall['skills']} |",
        (f"| Positives routed correctly (micro recall) | {overall['hits']}/{overall['positives']} "
        f"({overall['micro_recall']:.2f}) |"),
        f"| Mean per-skill recall (macro) | {overall['macro_recall']:.2f} |",
        f"| False-fire rate on generic requests | {ff['fired']}/{ff['negatives']} ({ff['rate']:.2f}) |",
        (f"| Skills never hit (recall 0) | {len(overall['skills_never_hit'])}: "
        f"{', '.join(overall['skills_never_hit']) or '-'} |"),
        f"| Refusals | {overall['refusals']} |",
        f"| Errors | {overall['errors']} |",
        "",
        "## Per-skill recall (worst first)",
        "",
        "| Skill | Positives | Hits | Recall | To none | Refused | Captured others' |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, row in ranked:
        lines.append(f"| {name} | {row['positives']} | {row['hits']} | {_fmt_recall(row['recall'])} | "
                     f"{row['to_none']} | {row['refused']} | {row['captured']} |")
    lines += ["", "## Confusion pairs (expected -> got)", ""]
    if report["confusion"]:
        lines += ["| Expected | Got | Count |", "|---|---|---|"]
        lines += [f"| {c['expected']} | {c['got']} | {c['count']} |" for c in report["confusion"]]
    else:
        lines.append("None.")
    lines += ["", f"## Missed positives ({len(report['misses'])})", ""]
    if report["misses"]:
        lines += ["| Item | Expected | Got | Request |", "|---|---|---|---|"]
        for miss in report["misses"]:
            got = miss["got"] + (f" ({miss['category']})" if miss.get("category") else "")
            request = miss["request"].replace("|", "\\|")
            lines.append(f"| {miss['id']} | {miss['expected']} | {got} | {request} |")
    else:
        lines.append("None.")
    lines += ["", f"## False fires ({ff['fired']}/{ff['negatives']})", ""]
    lines.append(f"False-fire rate: {ff['fired']}/{ff['negatives']} = {ff['rate']:.2f}.")
    if ff["fired_items"]:
        lines += ["", "| Request | Routed to |", "|---|---|"]
        lines += [f"| {item['request']} | {item['got']} |" for item in ff["fired_items"]]
    lines += ["", "## Caveats", "",
              ("- One run per request at low effort; treat single-item differences as noise and "
              "patterns (a skill at 0/3, a pair confused repeatedly) as signal."),
              ("- The router sees only the listing text. In the runtime the model also sees the "
              "conversation, tools, and rules, so absolute rates will differ; relative ranking is the evidence."),
              ("- Positives were written from the skill body, so a low recall means the body promises "
              "something the description does not say, or another description claims it first."),
              ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _latest_results(directory: Path) -> Path | None:
    candidates = sorted(directory.glob("results-*.json"))
    return candidates[-1] if candidates else None


def cmd_corpus(args) -> int:
    skills = load_skills(args.skills_dir)
    estimate = estimate_corpus_cost(skills, args.model)
    log(f"estimate: {estimate['requests']} generation requests, ~{estimate['input_tokens']} input tokens, "
        f"~{estimate['output_tokens_assumed']} output tokens each -> ${estimate['total_usd']:.2f}")
    if estimate["total_usd"] > args.max_cost:
        log(f"abort: estimate exceeds budget ${args.max_cost:.2f}; nothing sent")
        return 3
    client = make_client()
    corpus = build_corpus(skills, client, model=args.model, positives=args.positives, effort=args.effort,
                          concurrency=args.concurrency)
    _write_json(args.out, corpus)
    meta = corpus["meta"]
    log(f"wrote {args.out}: {len(corpus['items'])} items, ${meta['cost_usd']:.2f}, "
        f"{len(meta['generation_errors'])} generation error(s)")
    return 0


def cmd_route(args) -> int:
    skills = load_skills(args.skills_dir)
    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    client = make_client()
    try:
        results = route_corpus(corpus, skills, client, model=args.model, effort=args.effort,
                               concurrency=args.concurrency, limit=args.limit, max_cost_usd=args.max_cost,
                               output_tokens_assumed=args.output_tokens_assumed)
    except BudgetExceeded as exc:
        log(f"abort: {exc}")
        return 3
    out = Path(args.out) if args.out else EVAL_DIR / f"results-{results['meta']['date']}.json"
    _write_json(out, results)
    log(f"wrote {out}: {len(results['routes'])} routes, ${results['meta']['cost_usd']:.2f}"
        + (" (BUDGET EXCEEDED, partial)" if results["meta"]["budget_exceeded"] else ""))
    return 1 if results["meta"]["budget_exceeded"] else 0


def cmd_report(args) -> int:
    results_path = Path(args.results) if args.results else _latest_results(EVAL_DIR)
    if not results_path or not results_path.exists():
        log("error: no results file; run `route` first or pass --results")
        return 2
    results = json.loads(results_path.read_text(encoding="utf-8"))
    report = compute_report(results)
    results["report"] = report
    _write_json(results_path, results)
    readme = Path(args.readme)
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(render_readme(report, results["meta"], results_path.name), encoding="utf-8")
    overall = report["overall"]
    log(f"wrote {results_path.name} (report section) and {readme}: micro recall "
        f"{overall['hits']}/{overall['positives']}, macro {overall['macro_recall']:.2f}, "
        f"false-fire {report['false_fire']['fired']}/{report['false_fire']['negatives']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("corpus", help="generate the labelled request corpus")
    p.add_argument("--out", type=Path, default=CORPUS_PATH)
    p.add_argument("--model", default=CORPUS_MODEL)
    p.add_argument("--positives", type=int, default=POSITIVES_PER_SKILL)
    p.add_argument("--effort", default="medium")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD)
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser("route", help="route every corpus request with the cached skill table")
    p.add_argument("--corpus", default=str(CORPUS_PATH))
    p.add_argument("--out", default=None, help="default skills/_shared/description-eval/results-<date>.json")
    p.add_argument("--model", default=ROUTE_MODEL)
    p.add_argument("--effort", default="low")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--limit", type=int, default=None, help="route only the first N items (smoke test)")
    p.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD)
    p.add_argument("--output-tokens-assumed", type=int, default=OUTPUT_TOKENS_ASSUMED)
    p.set_defaults(func=cmd_route)

    p = sub.add_parser("report", help="compute recall / confusion / false-fire tables")
    p.add_argument("--results", default=None, help="default: newest results-*.json")
    p.add_argument("--readme", default=str(README_PATH))
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
