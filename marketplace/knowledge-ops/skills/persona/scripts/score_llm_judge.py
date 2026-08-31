"""LLM-as-judge scoring with pre-registered rubric.

Reads fixture.yaml and persona outputs. For each persona, sends the
output + rubric to a separate Anthropic SDK call (Opus 5 at high effort by
default — different from the persona model to decouple judging from dispatching).

Writes per-persona LLM-judge scores into each JSON file.

Per F6 finding: LLM-judge with strict rubric application is the
discriminating layer. Pair with keyword scoring; report Cohen's
kappa per RC via analyze.py.

Usage:
    python3 score_llm_judge.py <run-dir> [--fixture path]
                                       [--judge-model claude-opus-5]
                                       [--judge-effort high]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic
from model_runtime import (
    cache_matches_runtime,
    message_request,
    recommended_max_tokens,
    resolve_judge_effort,
    resolve_judge_model,
    runtime_receipt,
)


def load_fixture(path: Path) -> dict:
    if not path.exists():
        sys.exit(
            f"Fixture file not found: {path}\n"
            f"  Pass --fixture PATH or place fixture.yaml inside <run-dir>/."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"Could not read fixture {path}: {e}")
    try:
        import yaml
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            sys.exit(f"Fixture {path} is not valid YAML: {e}")
    except ImportError:
        sys.exit("PyYAML required. pip install pyyaml")


JUDGE_PROMPT_TEMPLATE = """You are an expert reviewer applying a strict
pre-registered rubric to a technical recommendation set produced by an
AI persona.

# Problem context

{problem}

# Known root causes (ground truth)

{rc_block}

# Known false leads (NOT fixes)

{fl_block}

# Your task

Read the recommendation set below and output a SINGLE JSON object with
EXACTLY these top-level keys (one per known root cause id, plus the
shared keys):

{rc_schema}
  "fl_endorsed": [list of FL ids endorsed-as-fix],
  "off_rubric_actionable_count": <int>,
  "off_rubric_examples": [up to 3 short quotes],
  "kappa_check_notes": "<one sentence on rubric ambiguity>"
}}

Be strict. "endorse" requires both criteria (a) AND (b) per the rubric.
"orthogonal" means the persona didn't engage with that root cause at all.
"absent" means the topic isn't mentioned.

Output ONLY the JSON object, no prose, no markdown fence.

# Recommendations to score

{output}
"""


def render_rc_block(rcs: dict) -> str:
    lines: list[str] = []
    for rc_id, rc_def in rcs.items():
        lines.append(f"**{rc_id.upper()} - {rc_def.get('short_name', rc_id)}**:")
        lines.append(rc_def.get("endorsement_criteria", ""))
        lines.append(rc_def.get("rejection_criteria", ""))
        lines.append("")
    return "\n".join(lines)


def render_rc_schema(rcs: dict) -> str:
    """Render the JSON schema block keyed by the fixture's actual RC ids.

    Replaces the hard-coded rc1/rc2/rc3 in the prompt template — fixtures
    with N != 3 RCs now produce a prompt that asks the judge for every
    RC the fixture defines (analyze.py iterates rc.lower() against this).
    Return is plain text (not a format string) — the surrounding template
    handles the opening "{" via .format()-escaped "{{".
    """
    lines: list[str] = ["{"]
    for rc_id in rcs:
        # Judge JSON uses lowercase keys to match analyze.py's rc.lower() lookup.
        lines.append(f'  "{rc_id.lower()}": "endorse | reject | orthogonal | absent",')
    return "\n".join(lines)


def render_fl_block(fls: dict) -> str:
    lines: list[str] = []
    for fl_id, fl_def in fls.items():
        lines.append(f"{fl_id}: {fl_def.get('short_name', fl_id)} — "
                     f"{fl_def.get('why_wrong', '')}")
    return "\n".join(lines)


def judge(client: anthropic.Anthropic, fixture: dict, persona_text: str,
           model: str, effort: str | None = None) -> dict:
    rcs = fixture.get("root_causes", {})
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        problem=fixture.get("problem", "")[:2000],
        rc_block=render_rc_block(rcs),
        rc_schema=render_rc_schema(rcs),
        fl_block=render_fl_block(fixture.get("false_leads", {})),
        output=persona_text,
    )
    t0 = time.time()
    try:
        request = message_request(
            model=model,
            max_tokens=recommended_max_tokens(
                workload="judge",
                model=model,
                effort=effort,
            ),
            messages=[{"role": "user", "content": prompt}],
            effort=effort,
        )
        resp = client.messages.create(**request)
        text = "".join(
            getattr(block, "text", "")
            for block in resp.content
            if getattr(block, "type", "text") == "text"
        )
        effective_model = getattr(resp, "model", None)
        stop_reason = getattr(resp, "stop_reason", None)
        receipt = runtime_receipt(
            requested_model=model,
            requested_effort=effort,
            effective_model=effective_model,
            stop_reason=stop_reason,
        )
        common = {
            "elapsed_s": round(time.time() - t0, 2),
            "model": effective_model or "<unavailable>",
            "requested_model": model,
            "effort": effort or "<unavailable>",
            "stop_reason": stop_reason or "<unavailable>",
            "runtime_receipt": receipt,
        }
        if effective_model is None:
            return {
                **common,
                "ok": False,
                "error_type": "model_unobserved",
                "error": (
                    "Anthropic response omitted model metadata; the judgment "
                    "cannot qualify the requested model lane"
                ),
            }
        if effective_model is not None and effective_model != model:
            return {
                **common,
                "ok": False,
                "error_type": "model_mismatch",
                "error": (
                    f"Requested {model}, but Anthropic returned {effective_model}; "
                    "judgment is not qualification evidence for the requested model"
                ),
            }
        if stop_reason == "refusal":
            return {
                **common,
                "ok": False,
                "error_type": "refusal",
                "error": "Anthropic model refused the rubric judgment",
            }
        if stop_reason in {"max_tokens", "model_context_window_exceeded"} or not text:
            reason = stop_reason if stop_reason != "end_turn" else "no_text_content"
            return {
                **common,
                "ok": False,
                "error_type": "incomplete_response",
                "error": f"Anthropic rubric judgment was incomplete: {reason}",
            }
        try:
            cleaned = re.sub(r"^```\w*\n?|\n?```$", "", text.strip(),
                              flags=re.MULTILINE)
            judgment = json.loads(cleaned)
        except json.JSONDecodeError as e:
            judgment = {"_parse_error": str(e), "_raw": text[:500]}
            return {
                **common,
                "ok": False,
                "error_type": "invalid_response",
                "error": "Anthropic rubric judgment was not valid JSON",
                "judgment": judgment,
                "raw": text,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
        return {
            **common,
            "ok": True,
            "judgment": judgment,
            "raw": text,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error_type": "transport_or_api",
            "error": str(e)[:300],
            "model": "<unavailable>",
            "requested_model": model,
            "effort": effort or "<unavailable>",
            "runtime_receipt": runtime_receipt(
                requested_model=model,
                requested_effort=effort,
            ),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--fixture", default=None)
    ap.add_argument("--judge-model", default=None)
    ap.add_argument(
        "--judge-effort",
        default=None,
        choices=["low", "medium", "high", "xhigh", "max"],
    )
    args = ap.parse_args()
    try:
        judge_model = resolve_judge_model(args.judge_model)
        judge_effort = resolve_judge_effort(args.judge_effort)
    except ValueError as exc:
        print(f"Persona judge runtime configuration error: {exc}", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    run_dir = Path(args.run_dir)
    fixture_path = Path(args.fixture) if args.fixture else run_dir / "fixture.yaml"
    fixture = load_fixture(fixture_path)

    client = anthropic.Anthropic()
    persona_dir = run_dir / "results-by-persona"
    n_inputs = 0
    n_attempted = 0
    n_succeeded = 0
    n_failed = 0
    for p in sorted(persona_dir.glob("persona_*.json")):
        n_inputs += 1
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: malformed persona JSON in {p}: {e}", file=sys.stderr)
            print("  hint: delete the corrupt file and re-run to re-dispatch "
                  "this persona.", file=sys.stderr)
            sys.exit(2)
        dispatch = rec.get("dispatch") or rec
        if not dispatch.get("ok"):
            n_failed += 1
            error_type = dispatch.get("error_type", "upstream_dispatch_failure")
            print(
                f"  failed: {p.name} (dispatch {error_type})",
                file=sys.stderr,
            )
            continue
        text = dispatch.get("text", "")
        rec.setdefault("scoring", {})
        # Skip ONLY if the cached result has both ok==True AND a parsed
        # judgment (i.e., not a stuck _parse_error). Without this guard,
        # JSON-decode failures persist as sticky state because the API
        # call succeeded — so re-runs never retry the bad parse.
        # (Ported from dispatch.py's rubric judge loop.)
        prior = rec["scoring"].get("llm_judge", {})
        prior_judgment = prior.get("judgment", {}) if isinstance(prior, dict) else {}
        if (prior.get("ok")
                and isinstance(prior_judgment, dict)
                and "_parse_error" not in prior_judgment
                and any(k.startswith("rc") for k in prior_judgment)
                and cache_matches_runtime(
                    prior,
                    requested_model=judge_model,
                    requested_effort=judge_effort,
                )):
            print(f"  cached: {p.name}")
            n_succeeded += 1
            continue
        print(f"  judging: {p.name}", flush=True)
        result = judge(
            client,
            fixture,
            text,
            judge_model,
            effort=judge_effort,
        )
        rec["scoring"]["llm_judge"] = result
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        n_attempted += 1
        if result.get("ok"):
            n_succeeded += 1
        else:
            n_failed += 1
            print(
                f"  failed: {p.name} "
                f"({result.get('error_type', 'unknown')})",
                file=sys.stderr,
            )

    if n_inputs == 0 or n_failed:
        print(
            "Persona judge failed closed: "
            f"inputs={n_inputs}, attempted={n_attempted}, "
            f"qualified={n_succeeded}, failed={n_failed}.",
            file=sys.stderr,
        )
        return 1

    print(
        "LLM-judge complete: "
        f"{n_succeeded} qualified persona outputs "
        f"({n_attempted} newly attempted)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
