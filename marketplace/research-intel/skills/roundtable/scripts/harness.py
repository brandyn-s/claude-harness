"""Generalized multi-agent adversarial roundtable harness.

Target-agnostic: pass any context file. Configurable rounds, agents,
auto-stop on convergence (Voyage embeddings), single-retry on transient
failures, JSONL persistence, null-control injection.

Usage:
    python3 harness.py --context CONTEXT.md --output ./results/ \
        [--max-rounds 5] [--no-prereg] [--inject-agent-d] \
        [--auto-stop] [--budget 30]

Output structure:
    results/
        round_1/{opus,grok,gpt[,agent_d]}.md
        round_2/main/{opus,grok,gpt}.md
        round_3/{prereg,main}/{opus,grok,gpt}.md
        round_4/{prereg,main}/{opus,grok,gpt}.md
        round_5/main/{opus,grok,gpt}.md
        transcript.jsonl
        convergence.json
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
TEMPLATES_DIR = SKILL_DIR / "templates" / "round_tasks"

sys.path.insert(0, str(SCRIPTS_DIR / "adapters"))
sys.path.insert(0, str(SCRIPTS_DIR))

import keychain  # noqa: E402
from adapters import anthropic_adapter, openai_adapter, xai_adapter  # noqa: E402
from embed import round_convergence, should_stop  # noqa: E402

# --- Base-token pricing per 1M tokens (rough tracking, not a billing oracle) ---
# Verified 2026-08-19: Fable 5 $10/$50 (Anthropic docs); grok-4.6 $2/$6
# short-context, $4/$12 at >=200k prompt tokens (docs.x.ai — the previous
# 125/250 figures here were ~100x above any published xAI rate); gpt-5.6-sol
# $5/$30 short-context, 2x in / 1.5x out for >272K-token prompts (OpenAI
# pricing page).
PRICING = {
    "opus": {"in": 10.0, "out": 50.0},
    "grok": {"in": 2.0, "out": 6.0},
    "gpt": {"in": 5.0, "out": 30.0},
}

ADAPTERS = {
    "opus": anthropic_adapter,
    "grok": xai_adapter,
    "gpt": openai_adapter,
}
PANEL_AGENTS = ("opus", "grok", "gpt")
MIN_PANEL_QUORUM = 2
UNAVAILABLE = "<unavailable>"

AGENT_LABELS = {
    "grok": "Agent GROK (xAI Grok 4.6)",
    "gpt": "Agent GPT (OpenAI GPT-5.6 Sol)",
}


def agent_label(agent: str) -> str:
    """Return a prompt label that reflects the requested model for this run."""
    if agent == "opus":
        return f"Agent OPUS (Anthropic {anthropic_adapter.resolve_model()})"
    return AGENT_LABELS[agent]

DEFAULT_MAX_TOKENS = {
    "main": {"opus": 4000, "grok": 4000, "gpt": 32000},
    "prereg": {"opus": 1500, "grok": 1500, "gpt": 8000},
}
# GPT (Responses API): max_output_tokens caps reasoning + visible tokens COMBINED, and
# at reasoning_effort="high" (the openai_adapter default) reasoning dominates.
# 8K and 16K both truncated on dense/open-ended contexts (status=incomplete,
# only a reasoning item, zero visible text). 32K gives headroom for worst-case
# high-effort reasoning + ~10-12K visible output; matches the openai_adapter
# default and the SKILL.md 24-32K guidance. The adapter now returns ok:False on
# incomplete (was a silent json fallback), so an under-budget GPT call surfaces
# as a loud FAIL instead of garbage. Root cause + probes: 2026-06-07
# /systematic-debugging (PR #1130).


def cost_estimate(in_tok: int, out_tok: int, agent: str, model: str | None = None) -> float:
    if agent == "opus":
        p = anthropic_adapter.pricing_for_model(model or anthropic_adapter.resolve_model())
    else:
        p = PRICING[agent]
    return (in_tok * p["in"] + out_tok * p["out"]) / 1_000_000


def jsonl_append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def call_agent(agent: str, prompt: str, max_tokens: int) -> dict:
    adapter = ADAPTERS[agent]
    return adapter.call(prompt, max_tokens=max_tokens)


def result_runtime_receipt(agent: str, result: dict) -> dict:
    """Normalize results without inferring context class from the requested arm."""
    existing = result.get("runtime_receipt")
    if isinstance(existing, dict):
        return existing

    requested_model = result.get("requested_model") or {
        "opus": anthropic_adapter.resolve_model(),
        "grok": xai_adapter.DEFAULT_MODEL,
        "gpt": openai_adapter.DEFAULT_MODEL,
    }[agent]
    effective_model = result.get("model")
    fallback = (
        effective_model != requested_model
        if effective_model is not None
        else UNAVAILABLE
    )
    effort = result.get("effort")
    if not effort and agent == "opus":
        effort = anthropic_adapter.resolve_effort()
    elif not effort and agent == "gpt":
        effort = "high"

    if result.get("error_type") == "refusal" or result.get("stop_reason") == "refusal":
        refusal = True
    elif result.get("ok") is True:
        refusal = False
    else:
        refusal = UNAVAILABLE

    return {
        "requested_model": requested_model,
        "requested_model_source": "request_configuration",
        "effective_model": effective_model or UNAVAILABLE,
        "effective_model_source": (
            "response_metadata" if effective_model is not None else "unavailable"
        ),
        "provider": {"opus": "anthropic", "grok": "xai", "gpt": "openai"}[agent],
        "effort": effort or UNAVAILABLE,
        "context_class": result.get("context_class") or UNAVAILABLE,
        "claude_code_version": UNAVAILABLE,
        "fallback": fallback,
        "switch_reason": (
            "provider_response_model_differs" if fallback is True else UNAVAILABLE
        ),
        "refusal": refusal,
    }


def successful_panel_agents(results: dict) -> tuple[str, ...]:
    """Return the distinct configured arms that produced usable output."""
    return tuple(
        agent
        for agent in PANEL_AGENTS
        if isinstance(results.get(agent), dict) and results[agent].get("ok") is True
    )


def panel_has_quorum(results: dict) -> bool:
    """A single surviving vendor is self-similarity, not panel consensus."""
    return len(successful_panel_agents(results)) >= MIN_PANEL_QUORUM


def record_quorum_abort(
    transcript_path: Path,
    *,
    round_num: int,
    results: dict,
    total_cost: float,
) -> None:
    """Write a typed terminal receipt for a collapsed main-round panel."""
    successful = successful_panel_agents(results)
    jsonl_append(transcript_path, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": "quorum_abort",
        "round": round_num,
        "successful_agents": list(successful),
        "required_agents": MIN_PANEL_QUORUM,
        "total_cost": round(total_cost, 2),
    })


def output_reuse_error(output_dir: Path, inject_agent_d: bool) -> str | None:
    """Reject mixed/replayed runs while allowing the documented Agent D seed."""
    if not output_dir.exists():
        return None
    if not output_dir.is_dir():
        return f"output path exists and is not a directory: {output_dir}"

    entries = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*")}
    if not entries:
        return None
    allowed_agent_d_seed = {"round_1", "round_1/agent_d.md"}
    if inject_agent_d and entries <= allowed_agent_d_seed:
        return None
    return (
        f"output directory is not empty: {output_dir}; choose a fresh directory "
        "so transcripts and model receipts cannot be mixed across runs"
    )


# Probe-before-panel: the pinned non-Anthropic arms are the exact class that
# silently invalidates a cross-model panel — a retired/silently-redirected model
# runs the whole roundtable under the wrong weights (the Nova-Pro confound
# rules/best-in-class-for-cross-model.md exists to prevent). Reuse the validated
# gather-vendor probe (sibling skill) rather than re-implementing the check.
_PROBE = SKILL_DIR.parent / "gather-vendor" / "scripts" / "probe_models.py"


def _panel_pins() -> dict:
    """Arm -> (probe vendor, pinned model id) read LIVE from each adapter so the
    preflight can never drift from what call_agent dispatches. Resolved lazily
    (not at import) with getattr fallback, so a missing/renamed DEFAULT_MODEL
    surfaces as a preflight warning rather than a NameError at module load —
    the exact class --skip-preflight exists to bypass."""
    pins = {}
    for arm, (vendor, adapter) in {"gpt": ("openai", openai_adapter),
                                   "grok": ("xai", xai_adapter)}.items():
        pins[arm] = (vendor, getattr(adapter, "DEFAULT_MODEL", None))
    return pins


def preflight_probe() -> tuple[list[str], list[str]]:
    """Probe every non-Anthropic panel pin.

    Returns (aborts, warns): `aborts` = retirement-class failures (probe exit 1)
    that invalidate the panel; `warns` = transient/auth-infra/skip conditions
    (probe exit 2, or a missing probe/adapter) that should NOT block a run.
    Never raises.
    """
    if not _PROBE.exists():
        return [], [f"preflight skipped: gather-vendor probe not found at {_PROBE}"]
    aborts, warns = [], []
    for arm, (vendor, model) in _panel_pins().items():
        if not model:
            warns.append(f"{arm} ({vendor}): adapter exposes no DEFAULT_MODEL — cannot probe")
            continue
        try:
            r = subprocess.run(
                [sys.executable, str(_PROBE), vendor, model],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:  # noqa: BLE001 — preflight must not kill the run
            warns.append(f"{arm} ({vendor} {model}): probe error {type(e).__name__}: {e} (transient?)")
            continue
        detail = (r.stdout + r.stderr).strip().splitlines()
        last = detail[-1] if detail else f"probe exit {r.returncode}"
        if r.returncode == 1:      # retirement class — invalidates the panel
            aborts.append(f"{arm} ({vendor} {model}): {last}")
        elif r.returncode != 0:    # transient / auth-infra — warn, do not abort
            warns.append(f"{arm} ({vendor} {model}): {last}")
    return aborts, warns


def round_ceiling() -> int:
    """Highest round number that has a task template on disk.

    Round 1 is built in code (build_round_1_prompt), round 2 uses
    round_2_critique.md, and rounds 3+ use round_N_main.md. Walk upward from 1
    until a main template is missing.

    WHY this is a preflight and not a runtime concern: --max-rounds is an
    unbounded int, and the template read that would fail sits inside the
    per-round prompt builder. So `--max-rounds 6` completed rounds 1-5, spent
    the entire budget, and only then raised FileNotFoundError. That leaves no
    terminal `run_complete` event in the transcript, and synthesize.py refuses
    any transcript whose terminal event is not `run_complete` — so the whole
    paid run became unsynthesizable. Validating up front turns a ~$30 loss into
    an instant, free error.
    """
    n = 1
    while True:
        nxt = n + 1
        name = "round_2_critique.md" if nxt == 2 else f"round_{nxt}_main.md"
        if not (TEMPLATES_DIR / name).is_file():
            return n
        n = nxt


def build_round_1_prompt(agent: str, context: str) -> str:
    """Round 1 = independent assessment.

    Includes a framing-audit step (added 2026-05-06): the context document
    may state inferences as if they were facts. Empirical example — the
    2026-05-06 code-search roundtable's context.md asserted "vector channel
    is the bottleneck (B1+D2 converge on this)". One agent anchored on
    this framing through 5 rounds; direct measurement (PR #127) later
    refuted it. The protocol-failure-mode #1 in that run's META_SYNTHESIS
    captured the lesson; this prompt step prevents recurrence by making
    the inference-vs-fact distinction explicit before the agent commits
    to a Round 1 stance. See:
    knowledge-base/topics/engineering-assessment-methodology.md
    section "Prompt-framing-as-evidence is an anti-pattern in adversarial
    reviews (2026-05-06)".
    """
    return f"""# Multi-agent adversarial roundtable — Round 1

You are {agent_label(agent)}. Two other agents will independently assess the same target. Round 1 is independent — you do not see the others' outputs until later rounds.

## Target context

{context}

## Pre-assessment framing audit (REQUIRED before your assessment)

The context document above may contain claims at two distinct epistemic levels, plus structural framings that count or label events. Distinguish all three before treating any claim as ground truth:

- **FACTS the context.md asserts**: measured numbers (e.g. "MRR=0.7380, n=183"), code excerpts with file:line citations, version IDs, dated empirical results, exact API responses. These are evidence.
- **INFERENCES the context.md draws**: claims like "X converges on Y", "A is the constraint", "B+C therefore D", or summaries that combine multiple facts into a conclusion. These are claims-under-adjudication, NOT evidence.
- **STRUCTURAL FRAMINGS the context.md uses**: section headers that count or categorize events ("Three executions of methodology X", "Five rounds of failure", "Two recurring patterns"). These framings can be wrong on arithmetic, not just on inference. Audit them: do the headers count what they claim to count? Empirical example — the 2026-05-08 /superplan roundtable's context labeled "Execution 3" as a separate methodology execution; only one of three agents in R1 caught that "Execution 3" was the same physical plan as Execution 2 with a better terminal doc, not a separate execution. Section-header framings get higher trust than they deserve.

For each inference and structural framing you identify, decide:
1. Does the cited evidence directly establish this claim/count, or
2. Does it require independent verification before it should ground further reasoning?

Open your assessment with a brief **"Framing audit"** section listing 1-3 load-bearing inferences AND any structural framings whose count/category you cannot verify from the cited evidence. Verdict on each: DIRECTLY ESTABLISHED / REQUIRES VERIFICATION / FRAMING WRONG. If you find no items worth flagging, say so explicitly. Do not proceed carrying claims forward as if they were facts.

Why this matters: refuting alternatives ≠ confirming a specific hypothesis. The data establishes what the data measures, not what the inference chain wants it to mean. Section headers establish what was structurally observed, not what the author claims was structurally observed. (Empirical: the 2026-05-06 code-search roundtable's "vector channel is the bottleneck (B1+D2 converge on this)" framing was refuted by a 3-minute direct measurement; the 2026-05-08 /superplan roundtable's "Execution 3" section header was a miscount only one agent caught.)

## Recommendation discipline (REQUIRED for any prescriptive output)

If your assessment will produce recommendations (e.g. "/superplan should add X", "the system needs Y", "the right threshold is N%"), each recommendation must meet the same evidence bar as the target's claims. Specifically:

- **Numeric thresholds** ("10%", "≥3 plans", "8 fields") must derive from arc data, not from intuition. Cite the failure case the threshold catches and the non-failure case it does not.
- **Taxonomies** ("the four failure modes", "the three patterns") must name the specific historical cases each category contains. A taxonomy that doesn't map to specific cases is a framing claim, not evidence.
- **Negative claims** ("no methodology could catch this", "this is impossible to prevent") require a counterfactual: under what conditions would the claim flip to "X methodology catches this"? If you cannot name the flip condition, downgrade to "I have not seen a methodology that catches this".
- **Falsifier required** on every load-bearing recommendation: a measurable condition that, if observed, invalidates your recommendation. "Add Phase 3.6" is incomplete; "Add Phase 3.6; falsifier = if 3 consecutive plans pass Phase 3.6 and still ship synthetic-only fixes, the gate is wrong-shaped" is complete.

The roundtable protocol's own 2026-05-08 execution discovered this: all 3 agents in R1 produced confident prescriptions (10% threshold, 8-field ledger, "no methodology could catch") without the evidence discipline they were demanding of the target. The methodology you're auditing requires a discipline you must also exercise.

## Your task

After the framing audit, provide a structured assessment. Be candid; do not flatter. Identify real issues with calibrated confidence.

Required structure:
- Framing audit (1-3 inferences/framings flagged or "nothing worth flagging")
- Major findings with confidence labels (HIGH/MEDIUM/LOW)
- Specific citations (file/symbol/line) where applicable
- For at least one finding: counterfactual ("if X were true, my conclusion would change")
- For every recommendation: derivation source (measured / extrapolated / estimated) AND falsifier

Length: 1000-1700 words (framing audit + recommendation discipline add ~250 words; main assessment unchanged). Direct prose. No padding.

You are {agent_label(agent)}.
"""


def build_round_n_prompt(agent: str, round_num: int, phase: str,
                          context: str, history_dir: Path,
                          inject_agent_d: bool,
                          task_template: str,
                          topology: str = "mesh",
                          anonymize_peers: bool = False) -> str:
    """Build prompt with prior round history.

    For prereg phase of round N: hide OTHER agents' main outputs of round N-1.

    topology="mesh" (default): each agent sees ALL peer outputs.
    topology="star": Opus is the central critic; Grok and GPT see only
    Opus's prior outputs (not each other's). Reduces non-critic prompt
    size by ~30-35% in R2+ at the cost of dropping direct Grok-GPT
    cross-exposure. Use only for cost-conscious runs.

    anonymize_peers=True: replace peer agent labels (model identity) with
    randomized "Agent A/B/C (anonymized)" per prompt build. Each agent's
    prompt gets its own shuffle, so peer A in Opus's view may be peer B
    in Grok's view. Reduces self-preference and cross-provider style bias
    (karpathy/llm-council pattern). The agent's OWN identity is unchanged
    (it still knows it's Opus/Grok/GPT). Untested empirically.
    """
    # Generate per-prompt anonymization mapping for peer outputs.
    if anonymize_peers:
        labels = ["Agent A (anonymized)", "Agent B (anonymized)",
                  "Agent C (anonymized)"]
        rnd = random.Random()
        rnd.shuffle(labels)
        anon_map = dict(zip(["opus", "grok", "gpt"], labels))
    else:
        anon_map = None

    def peer_label(a: str) -> str:
        if anon_map and a != agent and a in anon_map:
            return anon_map[a]
        return agent_label(a) if a in ADAPTERS else "Agent D (anonymous external reviewer)"

    parts = [
        f"# Multi-agent adversarial roundtable — Round {round_num} ({phase})",
        "",
        f"You are {agent_label(agent)}.",
    ]
    if anonymize_peers:
        parts.append("")
        parts.append("**Peer outputs in this prompt are anonymized.** Their "
                     "labels (Agent A/B/C) are randomized; you cannot tell "
                     "which model wrote which response. Critique on substance, "
                     "not on perceived model identity.")
    if phase == "prereg":
        parts.extend([
            "",
            "**This is the PRE-REGISTRATION substep.** You will write your "
            f"position on the Round {round_num} task BEFORE seeing the other "
            "agents' most recent round outputs. After this, you receive the "
            "others' outputs and write your full Round response. The pre-reg "
            "captures your position so we can measure the effect of cross-talk.",
            "",
            "**REQUIRED — predicted attack typing.** For each position you "
            "pre-register that you expect to defend, also state the TYPE of "
            "attack you predict the other agents will make. Choose one or "
            "more from:",
            "",
            "- `logical` — internal contradiction, mismatched premises, "
            "non-sequitur, scope-overreach (claim broader than evidence supports)",
            "- `evidentiary` — missing citation, single-source claim, stale "
            "evidence, evidence that doesn't establish the cited claim",
            "- `empirical` — direct measurement contradicts the claim "
            "(numbers, file:line citations, reproducible test)",
            "- `framing` — the claim's category or count is wrong (taxonomy "
            "mis-classification, structural framing miscount)",
            "",
            "Write the predicted-attack types as: `Predicted attack: logical, "
            "evidentiary` (or whatever applies). When the main phase produces "
            "the actual attacks, note whether the type matched. Mismatch "
            "between predicted and actual attack type is a calibration signal "
            "(2026-05-08 incident: Opus pre-registered evidentiary-attack "
            "defense; actual attack was logical/internal-contradiction; the "
            "pre-reg falsifier was wrong-typed and added less calibration "
            "value than expected).",
        ])
    parts.extend([
        "",
        "## Target context",
        "",
        context,
        "",
        "---",
        "",
    ])

    # Star topology: when agent is a non-critic (Grok or GPT), hide other
    # non-critic outputs from peer history. Opus's prompts unchanged.
    def _star_hidden(peer: str) -> bool:
        return (topology == "star"
                and agent != "opus"
                and peer != "opus"
                and peer != agent)

    # Embed prior rounds. Filter out OTHERS' main of round N-1 during prereg.
    for r in range(1, round_num + (0 if phase == "prereg" else 1)):
        if r == 1:
            agents_for_r1 = ["opus", "grok", "gpt"] + (["agent_d"] if inject_agent_d else [])
            parts.append("## ROUND 1 — independent assessments")
            parts.append("")
            for a in agents_for_r1:
                if _star_hidden(a):
                    continue
                path = history_dir / "round_1" / f"{a}.md"
                if not path.exists():
                    continue
                label = peer_label(a)
                parts.append(f"### {label} — Round 1")
                parts.append("")
                if a == agent:
                    parts.append("**(THIS WAS YOUR OUTPUT)**")
                    parts.append("")
                parts.append(path.read_text(encoding="utf-8"))
                parts.append("")
            parts.append("---")
            parts.append("")
        else:
            for sub_phase in (["prereg", "main"] if r >= 3 else ["main"]):
                parts.append(f"## ROUND {r} ({sub_phase}) — agent outputs")
                parts.append("")
                for a in ["opus", "grok", "gpt"]:
                    if _star_hidden(a):
                        continue
                    path = history_dir / f"round_{r}" / sub_phase / f"{a}.md"
                    if not path.exists():
                        continue
                    # Hide others' main of round N-1 during prereg of round N
                    if (phase == "prereg"
                            and r == round_num - 1
                            and sub_phase == "main"
                            and a != agent):
                        parts.append(f"### {peer_label(a)} — Round {r} ({sub_phase})")
                        parts.append("")
                        parts.append("*[hidden during your pre-registration; visible after submission]*")
                        parts.append("")
                        continue
                    parts.append(f"### {peer_label(a)} — Round {r} ({sub_phase})")
                    parts.append("")
                    if a == agent:
                        parts.append("**(THIS WAS YOUR OUTPUT)**")
                        parts.append("")
                    parts.append(path.read_text(encoding="utf-8"))
                    parts.append("")
                parts.append("---")
                parts.append("")

    parts.extend([
        f"## ROUND {round_num} ({phase}) — YOUR TASK",
        "",
        task_template,
        "",
        f"You are {agent_label(agent)}. Respond directly. Do not pad or flatter.",
    ])
    return "\n".join(parts)


def run_phase(round_num: int, phase: str,
              context: str, output_dir: Path,
              transcript_path: Path,
              inject_agent_d: bool = False,
              budget_remaining: float | None = None,
              topology: str = "mesh",
              anonymize_peers: bool = False) -> tuple[dict, float]:
    """Execute one round-phase. Returns (per-agent results, cost spent)."""
    if round_num == 1:
        # Round 1: independent
        prompts = {a: build_round_1_prompt(a, context) for a in ["opus", "grok", "gpt"]}
        out_dir = output_dir / "round_1"
    else:
        task_path = TEMPLATES_DIR / f"round_{round_num}_{phase if phase != 'main' else 'critique' if round_num == 2 else 'main'}.md"
        # Map: round_2_main -> round_2_critique.md; round_3_main -> round_3_main.md; etc.
        if round_num == 2:
            task_path = TEMPLATES_DIR / "round_2_critique.md"
        elif phase == "prereg":
            task_path = TEMPLATES_DIR / f"round_{round_num}_prereg.md"
        else:
            task_path = TEMPLATES_DIR / f"round_{round_num}_main.md"

        if not task_path.exists():
            raise FileNotFoundError(f"Missing task template: {task_path}")
        task = task_path.read_text(encoding="utf-8")
        prompts = {a: build_round_n_prompt(a, round_num, phase, context,
                                             output_dir, inject_agent_d, task,
                                             topology=topology,
                                             anonymize_peers=anonymize_peers)
                   for a in PANEL_AGENTS}
        out_dir = (output_dir / f"round_{round_num}" / phase
                   if round_num >= 3 and phase == "prereg"
                   else output_dir / f"round_{round_num}" / "main"
                   if round_num >= 2
                   else output_dir / f"round_{round_num}")

    out_dir.mkdir(parents=True, exist_ok=True)

    workload = phase if phase == "prereg" else "main"
    max_tokens = dict(DEFAULT_MAX_TOKENS[workload])
    max_tokens["opus"] = anthropic_adapter.recommended_max_tokens(workload)

    print(f"\n=== Round {round_num} ({phase}) ===")
    for a, p in prompts.items():
        print(f"  {a}: prompt size = {len(p)} chars")

    results = {}
    phase_cost = 0.0

    def call_one(agent):
        return agent, call_agent(agent, prompts[agent], max_tokens[agent])

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(call_one, a) for a in PANEL_AGENTS]
        for fut in concurrent.futures.as_completed(futures):
            agent, result = fut.result()
            result = dict(result)
            receipt = result_runtime_receipt(agent, result)
            result["runtime_receipt"] = receipt
            if result.get("ok") is True and receipt.get("fallback") is True:
                result.update({
                    "ok": False,
                    "error_type": "model_switch",
                    "error": (
                        "provider response model differed from requested panel arm: "
                        f"requested={receipt['requested_model']}, "
                        f"effective={receipt['effective_model']}"
                    ),
                })
            results[agent] = result
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            if result["ok"]:
                cost = cost_estimate(
                    result["input_tokens"], result["output_tokens"], agent,
                    model=result.get("model"),
                )
                phase_cost += cost
                retried = " (retried)" if result.get("retried") else ""
                print(f"  {agent}: OK | in={result['input_tokens']} out={result['output_tokens']} "
                      f"elapsed={result['elapsed_s']}s ~${cost:.3f}{retried}")
                # Write output file
                fname = f"{agent}.md"
                out_path = out_dir / fname
                with open(out_path, "w", encoding="utf-8") as fh:
                    fh.write(f"# {agent.upper()} — Round {round_num} ({phase})\n\n")
                    fh.write(f"Model: {result.get('model', 'unknown')} | "
                             f"Tokens: in={result['input_tokens']} out={result['output_tokens']} | "
                             f"Cost: ~${cost:.3f} | Elapsed: {result['elapsed_s']}s"
                             f"{retried}\n\n")
                    fh.write("---\n\n")
                    fh.write(result["text"])
                # JSONL record
                jsonl_append(transcript_path, {
                    "ts": ts,
                    "round": round_num,
                    "phase": phase,
                    "agent": agent,
                    "requested_model": result.get("requested_model"),
                    "model": result.get("model"),
                    "effort": result.get("effort"),
                    "stop_reason": result.get("stop_reason"),
                    "prompt_chars": len(prompts[agent]),
                    "input_tokens": result["input_tokens"],
                    "output_tokens": result["output_tokens"],
                    "elapsed_s": result["elapsed_s"],
                    "cost_usd": round(cost, 4),
                    "retried": result.get("retried", False),
                    "ok": True,
                    "text": result["text"],
                    "runtime_receipt": result["runtime_receipt"],
                })
            else:
                print(f"  {agent}: FAIL | {result.get('error', '')[:200]}")
                jsonl_append(transcript_path, {
                    "ts": ts,
                    "round": round_num,
                    "phase": phase,
                    "agent": agent,
                    "requested_model": result.get("requested_model"),
                    "model": result.get("model"),
                    "ok": False,
                    "error_type": result.get("error_type"),
                    "stop_reason": result.get("stop_reason"),
                    "stop_details": result.get("stop_details"),
                    "error": result.get("error", ""),
                    "elapsed_s": result.get("elapsed_s"),
                    "runtime_receipt": result["runtime_receipt"],
                })

    print(f"  Phase cost: ${phase_cost:.2f}")
    return results, phase_cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True, help="Path to target context markdown file")
    ap.add_argument("--output", required=True, help="Output directory")
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--min-rounds", type=int, default=3,
                     help="Minimum rounds before auto-stop is allowed (default 3)")
    ap.add_argument("--no-prereg", action="store_true",
                     help="Skip pre-registration substeps in rounds 3-4")
    ap.add_argument("--inject-agent-d", action=argparse.BooleanOptionalAction,
                     default=True,
                     help="Inject fabricated null-control agent D in Round 1. ON BY "
                          "DEFAULT: it is the only instrument that detects placebo "
                          "agreement (arms endorsing a fabricated peer's invented "
                          "citations). The round_sycophancy metric covers "
                          "caving-without-evidence but is blind to this mode, so "
                          "without D a convergent finding cannot be distinguished "
                          "from correlated credulity. Requires a pre-seeded "
                          "round_1/agent_d.md in the output dir; author it from "
                          "templates/agent_d_template.md. Pass --no-inject-agent-d "
                          "to run without the control and accept that limitation.")
    ap.add_argument("--auto-stop", action="store_true",
                     help="Stop early if all agents have output cosine sim >= "
                          "threshold to prior round (requires VOYAGE_API_KEY)")
    ap.add_argument("--convergence-threshold", type=float, default=0.92)
    ap.add_argument("--budget", type=float, default=None,
                     help="Abort if projected cost exceeds USD budget")
    ap.add_argument("--topology", choices=["mesh", "star"], default="mesh",
                     help="Communication topology for R2+. mesh (default): all "
                          "agents see all peers. star: Opus is central critic; "
                          "Grok and GPT see only Opus's prior outputs (~25%% "
                          "cheaper but loses direct Grok-GPT cross-exposure).")
    ap.add_argument("--anonymize-peers", action="store_true",
                     help="Replace peer agent labels with randomized 'Agent A/B/C "
                          "(anonymized)' per prompt. Reduces self-preference and "
                          "cross-provider style bias (karpathy/llm-council pattern). "
                          "Untested empirically; runbook #2 ablation pending.")
    ap.add_argument("--skip-preflight", action="store_true",
                     help="Skip the probe-before-panel check of the pinned GPT/Grok "
                          "arms. Default is to abort if a pinned model is retired or "
                          "silently redirected (a wrong-weights arm invalidates the "
                          "cross-model panel).")
    args = ap.parse_args()

    context_path = Path(args.context)
    output_dir = Path(args.output)

    if not context_path.exists():
        sys.exit(f"Context file not found: {context_path}")

    # Round ceiling: reject an unrunnable round count BEFORE spending anything.
    ceiling = round_ceiling()
    if args.max_rounds < 1:
        sys.exit(f"--max-rounds must be >= 1 (got {args.max_rounds})")
    if args.max_rounds > ceiling:
        sys.exit(
            f"--max-rounds {args.max_rounds} exceeds the protocol ceiling of {ceiling}: "
            f"no task template exists for round {ceiling + 1} "
            f"({TEMPLATES_DIR}). Rounds past the ceiling would spend the full budget "
            f"and then crash without a terminal run_complete receipt, making the run "
            f"unsynthesizable. The protocol is defined through round {ceiling}; the v2 "
            f"experiment measured zero prereg->main information gain at round 5, so "
            f"additional rounds are also the lowest-value part of the curve."
        )

    reuse_error = output_reuse_error(output_dir, args.inject_agent_d)
    if reuse_error:
        print(f"error: {reuse_error}", file=sys.stderr)
        return 2
    # Check the only permitted seed before creating a transcript. Otherwise a
    # first attempt without Agent D would poison its own output directory and
    # the reuse guard would reject the instructed rerun.
    if args.inject_agent_d:
        agent_d_path = output_dir / "round_1" / "agent_d.md"
        if not agent_d_path.is_file():
            print(f"ℹ Agent D injection requested but {agent_d_path} not found.")
            print(f"  Template guidance at: {SKILL_DIR / 'templates' / 'agent_d_template.md'}")
            print("  Generate one (using the orchestrating model in your shell or chat) and place at:")
            print(f"    {agent_d_path}")
            print("  Then re-run.")
            return 2
    # Resolve provider keys from the Keychain so the operator never has to inline
    # secrets at the invocation site. Values are never printed — only the source.
    #
    # ORDERING (moved below the two cheap return-2 guards above, 2026-08-30): this
    # must run before any provider dispatch, and it still does — preflight_probe()
    # and run_phase() are both below. But it must run AFTER the guards that cost
    # nothing, for two reasons. Operator-facing: with a reused output dir AND a
    # missing key, aborting on the key first hides the dir problem until the key is
    # fixed, so the operator pays two round-trips to learn both. Structural: those
    # guards deliberately fire before the output dir is created — the comment above
    # exists because a run that poisons its own dir makes the instructed rerun
    # impossible — and a credential abort ahead of them defeats that ordering.
    #
    # Placing it first also broke 7 tests on the keyless CI runner, which is how
    # the ordering was noticed; the tests are the symptom, not the reason. This
    # move restores 2 of them (the guard tests, which now reach their guard); the
    # other 5 traverse past this point with dispatch stubbed and are handed
    # sentinel keys by the `stub_panel_credentials` fixture in tests/conftest.py.
    for line in keychain.load_keys():
        print(f"KEY: {line}", file=sys.stderr)
    absent = keychain.missing_required()
    if absent:
        sys.exit(
            "Aborting: no credential resolved for " + ", ".join(absent) + ". "
            "A missing key fails that arm and silently reduces the cross-model "
            "panel, which invalidates the decorrelated-consensus claim. Add the "
            "Keychain item or export the env var, then re-run."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    context = context_path.read_text(encoding="utf-8")

    # Probe-before-panel: verify the pinned non-Anthropic arms resolve (and are
    # not silently redirected) BEFORE spending 5 rounds of API. A retirement-class
    # failure invalidates cross-model validity -> abort. Transient/auth-infra/skip
    # conditions only warn (a 30s vendor blip or an env-vs-Keychain key mismatch
    # must not train operators to reach for --skip-preflight).
    if not args.skip_preflight:
        aborts, warns = preflight_probe()
        for line in warns:
            print(f"PREFLIGHT WARNING: {line}", file=sys.stderr)
        if aborts:
            print("PREFLIGHT FAILED — pinned panel arm(s) retired/redirected:", file=sys.stderr)
            for line in aborts:
                print(f"  - {line}", file=sys.stderr)
            sys.exit("Aborting: run /gather-vendor <vendor> to resolve, or pass "
                     "--skip-preflight to run anyway (cross-model validity not guaranteed).")

    transcript_path = output_dir / "transcript.jsonl"
    convergence_path = output_dir / "convergence.json"

    # Init transcript
    if not transcript_path.exists():
        requested_anthropic_model = anthropic_adapter.resolve_model()
        requested_anthropic_effort = anthropic_adapter.resolve_effort()
        jsonl_append(transcript_path, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "run_start",
            "anthropic_model": requested_anthropic_model,
            "anthropic_effort": requested_anthropic_effort,
            "runtime_receipt": anthropic_adapter.runtime_receipt(
                requested_model=requested_anthropic_model,
                effort=requested_anthropic_effort,
            ),
            "context_file": str(context_path),
            "context_chars": len(context),
            "max_rounds": args.max_rounds,
            "no_prereg": args.no_prereg,
            "inject_agent_d": args.inject_agent_d,
            "auto_stop": args.auto_stop,
            "budget": args.budget,
            "topology": args.topology,
            "anonymize_peers": args.anonymize_peers,
        })

    convergence_log = {}
    total_cost = 0.0
    r = 1  # initialize for the unbound case where loop doesn't execute

    # === Round 1 ===
    round_results, c1 = run_phase(
        1, "main", context, output_dir, transcript_path,
        inject_agent_d=args.inject_agent_d,
        topology=args.topology,
        anonymize_peers=args.anonymize_peers,
    )
    total_cost += c1
    if not panel_has_quorum(round_results):
        survivors = ", ".join(successful_panel_agents(round_results)) or "none"
        print(
            f"Panel quorum collapsed after Round 1: {survivors}; "
            f"need {MIN_PANEL_QUORUM} distinct successful vendors. Aborting.",
            file=sys.stderr,
        )
        record_quorum_abort(
            transcript_path,
            round_num=1,
            results=round_results,
            total_cost=total_cost,
        )
        convergence_path.write_text("{}\n", encoding="utf-8")
        return 2
    if args.budget and total_cost > args.budget:
        print(f"⚠ Budget exceeded after Round 1: ${total_cost:.2f} > ${args.budget}. Aborting.")
        convergence_path.write_text(json.dumps(convergence_log, indent=2), encoding="utf-8")
        jsonl_append(transcript_path, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": "budget_abort",
            "round": 1,
            "total_cost": round(total_cost, 2),
        })
        return 0

    # === Rounds 2..max ===
    for r in range(2, args.max_rounds + 1):
        # Pre-reg substep for rounds 3 and 4 (skip R5 prereg per v2 finding).
        # Its cost MUST be accumulated: total_cost is the same variable --budget
        # is enforced against below, so discarding the prereg return value made
        # the budget guard blind to real spend. Measured 2026-08-30 on a 5-round
        # run: 6 prereg calls cost $1.24 of $5.45 actual (23%), while the run
        # reported $4.22 -- so a --budget 30 run could have spent ~$39 without
        # tripping the guard, and every historical cost figure produced by this
        # harness under-reports by its prereg share.
        if r in (3, 4) and not args.no_prereg:
            _prereg_results, prereg_cost = run_phase(
                r, "prereg", context, output_dir, transcript_path,
                inject_agent_d=args.inject_agent_d,
                topology=args.topology,
                anonymize_peers=args.anonymize_peers,
            )
            total_cost += prereg_cost

        # Main phase
        round_results, cost = run_phase(
            r, "main", context, output_dir, transcript_path,
            inject_agent_d=args.inject_agent_d,
            topology=args.topology,
            anonymize_peers=args.anonymize_peers,
        )
        total_cost += cost
        if not panel_has_quorum(round_results):
            survivors = ", ".join(successful_panel_agents(round_results)) or "none"
            print(
                f"Panel quorum collapsed after Round {r}: {survivors}; "
                f"need {MIN_PANEL_QUORUM} distinct successful vendors. Aborting.",
                file=sys.stderr,
            )
            record_quorum_abort(
                transcript_path,
                round_num=r,
                results=round_results,
                total_cost=total_cost,
            )
            convergence_path.write_text(
                json.dumps(convergence_log, indent=2) + "\n",
                encoding="utf-8",
            )
            return 2

        # Auto-stop: check convergence vs prior round
        if args.auto_stop and r >= args.min_rounds:
            prior_outputs = {}
            current_outputs = {}
            for a in PANEL_AGENTS:
                # Round 1 has no prereg/main split — writes directly to
                # round_1/{a}.md (see line ~333). All later rounds split
                # into prereg/main subdirs.
                if r - 1 == 1:
                    prior_path = output_dir / "round_1" / f"{a}.md"
                else:
                    prior_path = output_dir / f"round_{r-1}" / "main" / f"{a}.md"
                curr_path = output_dir / f"round_{r}" / "main" / f"{a}.md"
                if prior_path.exists() and curr_path.exists():
                    prior_outputs[a] = prior_path.read_text(encoding="utf-8")
                    current_outputs[a] = curr_path.read_text(encoding="utf-8")
            sims = round_convergence(prior_outputs, current_outputs)
            stop, reason = should_stop(r, args.min_rounds,
                                         args.convergence_threshold, sims)
            convergence_log[f"round_{r}"] = {"sims": sims, "stop": stop, "reason": reason}
            print(f"  Convergence: {reason}")
            if stop:
                print(f"  Auto-stopping at round {r}.")
                convergence_path.write_text(json.dumps(convergence_log, indent=2),
                                              encoding="utf-8")
                jsonl_append(transcript_path, {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "event": "auto_stop",
                    "round": r,
                    "reason": reason,
                    "total_cost": round(total_cost, 2),
                })
                break

        if args.budget and total_cost > args.budget:
            print(f"⚠ Budget exceeded after round {r}: ${total_cost:.2f} > ${args.budget}. Aborting.")
            convergence_path.write_text(
                json.dumps(convergence_log, indent=2) + "\n",
                encoding="utf-8",
            )
            jsonl_append(transcript_path, {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "event": "budget_abort",
                "round": r,
                "total_cost": round(total_cost, 2),
            })
            return 0

    convergence_path.write_text(json.dumps(convergence_log, indent=2), encoding="utf-8")
    jsonl_append(transcript_path, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": "run_complete",
        "total_cost": round(total_cost, 2),
        "rounds_executed": r,
    })

    print("\n=== Run complete ===")
    print(f"Total cost: ${total_cost:.2f}")
    print(f"Outputs at: {output_dir}")
    print("\nNext step: run synthesize.py to produce META_SYNTHESIS.md")
    print(f"  python3 {SCRIPTS_DIR / 'synthesize.py'} --output {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
