"""Final synthesis pass using the configured roundtable Anthropic model.

Reads all round outputs in the run directory and produces a structured
synthesis: convergent findings, divergent positions, single-source items,
top-3 recommendations, round-by-round delta analysis.
"""
import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR / "adapters"))
sys.path.insert(0, str(SCRIPTS_DIR))

import keychain  # noqa: E402
from adapters import anthropic_adapter, openai_adapter, xai_adapter  # noqa: E402


SYNTHESIS_PROMPT = """You are synthesizing the results of a multi-agent adversarial roundtable on a target context. The configured three-arm panel was {anthropic_model}, {grok_model}, and {gpt_model}. Successful main-round coverage was {coverage_summary}. The panel then engaged in {rounds_completed} rounds after Round 1. Pre-registration substeps {prereg_status}. Null-control Agent D {agent_d_status}.

Coverage contract: {coverage_contract}. Never claim 3-of-3 agreement unless all three configured arms produced successful output in every main round. For each finding, name the successful arms and rounds that actually support it; a quorum is not evidence that every surviving arm agreed.

Your task: produce META_SYNTHESIS.md covering:

{agreement_heading}
Findings that survived all rounds without successful counter-argument from any agent. List each with the citation that supports it and the round where it stabilized.

## Divergent findings (genuine remaining disagreements)
Claims where 2+ agents differ AFTER Round 4 resolution attempts. List each with positions per agent and the resolution path proposed in Round 4.

## Single-source findings (LOW-MEDIUM confidence — needs verification)
Findings raised by only one agent that were not fully cross-verified. Flag each for source verification.

For each single-source finding, classify by what's needed to resolve:
- **Resolvable by cross-talk** — another round of agent engagement could in-principle confirm or refute. (Most single-source findings.)
- **Requires primary evidence** — resolution requires direct inspection of source documents, code files, measurement data, or logs that are NOT in the supplied context. The roundtable protocol cannot adjudicate these by adding rounds; cost will keep climbing without progress.

For findings tagged **Requires primary evidence**, recommend an EARLY EXIT verdict in this synthesis: name the specific document/code/data the user (or main-thread) must fetch to resolve, and recommend NOT running additional rounds against this finding. Empirical example: the 2026-05-08 /superplan roundtable's narrative-inheritance claim required reading pre-PR-854 plan files; 5 rounds of cross-talk could not resolve it because no agent had the documents in context. The 5-round runs cost was wasted on this finding alone; an early-exit verdict would have saved ~$8 of compute and surfaced the resolution path immediately.

## NEW findings that emerged from cross-talk
Items no agent stated in Round 1 but became visible only because the agents engaged with each other. Cite the exchange that surfaced them.

## Round-by-round delta analysis (if pre-reg ran)
- R3: which agents conceded between pre-reg and main? Calibration signal.
- R4: which predicted disagreements survived?
- R5: how much did final positions differ from earlier rounds? (Convergence vs conformity check.)

## Agent D commentary (if null-control was active)
What did the roundtable conclude about Agent D? Were the fabrications detected? Which agent was most/least vulnerable?

## Top-3 recommendations
Post-cross-talk priority list with confidence labels and rough cost/effort estimates.

## Protocol failure modes
What went wrong with the protocol itself? Bandwidth differences, network issues, single-source biases, etc.

---

# Round outputs (full transcript)

{round_dump}

---

Length: 1500-2500 words. Direct prose. Use clear section headers. Be specific about which agent said what. Do not flatter.
"""


def read_transcript_metadata(transcript: Path) -> dict:
    """Read run controls and effective participant models from its receipt log."""
    metadata = {
        "prereg_used": False,
        "agent_d_used": False,
        "rounds_completed": 0,
        "total_cost": 0.0,
        "participant_models": {"opus": set(), "grok": set(), "gpt": set()},
        "main_agents_by_round": {},
        "run_anthropic_model": None,
        "run_anthropic_effort": None,
        "terminal_event": None,
    }
    if not transcript.exists():
        return metadata

    with transcript.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            # Synthesis authorization is bound to the physical transcript
            # boundary, not merely to the presence of a run_complete event
            # somewhere earlier in a contaminated or resumed log.
            metadata["terminal_event"] = rec.get("event")
            receipt = (
                rec.get("runtime_receipt")
                if isinstance(rec.get("runtime_receipt"), dict)
                else {}
            )
            if rec.get("event") == "run_start":
                metadata["prereg_used"] = not rec.get("no_prereg", False)
                metadata["agent_d_used"] = rec.get("inject_agent_d", False)
                metadata["run_anthropic_model"] = (
                    receipt.get("requested_model") or rec.get("anthropic_model")
                )
                metadata["run_anthropic_effort"] = (
                    receipt.get("effort") or rec.get("anthropic_effort")
                )
            if rec.get("event") == "quorum_abort":
                round_num = rec.get("round")
                if isinstance(round_num, int) and round_num > 0:
                    metadata["rounds_completed"] = max(
                        metadata["rounds_completed"], round_num
                    )
                    metadata["main_agents_by_round"][round_num] = {
                        agent
                        for agent in rec.get("successful_agents", [])
                        if agent in metadata["participant_models"]
                    }
            phase = rec.get("phase", "main")
            if "round" in rec and rec.get("ok") and phase == "main":
                metadata["rounds_completed"] = max(
                    metadata["rounds_completed"], rec["round"]
                )
                agent = rec.get("agent")
                model = receipt.get("effective_model") or rec.get("model")
                if model == "<unavailable>":
                    model = None
                if agent in metadata["participant_models"] and model:
                    metadata["participant_models"][agent].add(model)
                if agent in metadata["participant_models"]:
                    metadata["main_agents_by_round"].setdefault(
                        rec["round"], set()
                    ).add(agent)
            if "total_cost" in rec:
                metadata["total_cost"] = rec["total_cost"]
    return metadata


def _model_label(models: set[str], fallback: str) -> str:
    return " / ".join(sorted(models)) if models else fallback


def coverage_summary(metadata: dict) -> str:
    """Format the exact successful arm set for every completed main round."""
    rounds_completed = metadata["rounds_completed"]
    by_round = metadata["main_agents_by_round"]
    return "; ".join(
        f"R{round_num}="
        + (",".join(sorted(by_round.get(round_num, set()))) or "none")
        for round_num in range(1, rounds_completed + 1)
    )


def coverage_contract(metadata: dict) -> tuple[bool, str, str]:
    """Return validity, prompt contract, and evidence-qualified heading."""
    expected = {"opus", "grok", "gpt"}
    rounds_completed = metadata["rounds_completed"]
    by_round = metadata["main_agents_by_round"]
    counts = [len(by_round.get(r, set())) for r in range(1, rounds_completed + 1)]
    if not counts or min(counts) < 2:
        return (
            False,
            "INVALID: at least one main round has fewer than two successful vendor arms",
            "## Convergent findings (INVALID PANEL — synthesis must stop)",
        )
    if all(by_round.get(r, set()) == expected for r in range(1, rounds_completed + 1)):
        return (
            True,
            "All three configured arms succeeded in every main round; 3-of-3 claims still require finding-level support from each arm",
            "## Convergent findings (3-of-3 eligible; verify finding-level support)",
        )
    return (
        True,
        "At least two arms succeeded in every main round, but one or more rounds lacked an arm; do not claim 3-of-3",
        "## Convergent findings (quorum-supported; coverage-qualified confidence)",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, help="Roundtable output directory")
    args = ap.parse_args()

    output_dir = Path(args.output)
    if not output_dir.exists():
        sys.exit(f"Output dir not found: {output_dir}")

    # Synthesis dispatches the Anthropic arm, so it needs that credential. Resolve
    # it the same way the harness does rather than requiring the operator to inline
    # a secret at the invocation site.
    for line in keychain.load_keys(keychain.SYNTHESIS_KEYS):
        print(f"KEY: {line}", file=sys.stderr)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Aborting: no ANTHROPIC_API_KEY resolved from env or Keychain.")

    # Gather round metadata and the models that actually produced the run.
    transcript = output_dir / "transcript.jsonl"
    metadata = read_transcript_metadata(transcript)
    prereg_used = metadata["prereg_used"]
    agent_d_used = metadata["agent_d_used"]
    rounds_completed = metadata["rounds_completed"]
    total_cost = metadata["total_cost"]
    participant_models = metadata["participant_models"]
    run_anthropic_model = metadata["run_anthropic_model"]
    run_anthropic_effort = metadata["run_anthropic_effort"]
    coverage = coverage_summary(metadata)
    coverage_valid, contract, agreement_heading = coverage_contract(metadata)

    # Build round dump
    parts = []
    for r in range(1, rounds_completed + 1):
        if r == 1:
            parts.append("# ROUND 1 — Independent assessments")
            for a in ["opus", "grok", "gpt"] + (["agent_d"] if agent_d_used else []):
                p = output_dir / "round_1" / f"{a}.md"
                if p.exists():
                    parts.append(f"\n## Agent: {a}\n")
                    parts.append(p.read_text(encoding="utf-8"))
        else:
            for phase in (["prereg", "main"] if r >= 3 else ["main"]):
                phase_dir = output_dir / f"round_{r}" / phase
                if not phase_dir.exists():
                    continue
                parts.append(f"\n# ROUND {r} ({phase})")
                for a in ["opus", "grok", "gpt"]:
                    p = phase_dir / f"{a}.md"
                    if p.exists():
                        parts.append(f"\n## Agent: {a}\n")
                        parts.append(p.read_text(encoding="utf-8"))

    round_dump = "\n".join(parts)

    if rounds_completed == 0 or not round_dump.strip():
        print(f"error: no round outputs found in {output_dir}", file=sys.stderr)
        print("hint: run the roundtable harness first so the run directory "
              "contains transcript.jsonl and round_*/ agent outputs",
              file=sys.stderr)
        return 2
    if metadata["terminal_event"] != "run_complete":
        print(
            "error: transcript has no terminal run_complete receipt; "
            "refusing synthesis of a running, crashed, or aborted panel",
            file=sys.stderr,
        )
        return 2
    if not coverage_valid:
        print(
            f"error: cannot synthesize a collapsed panel ({coverage or 'no main-round coverage'})",
            file=sys.stderr,
        )
        return 2
    if not run_anthropic_model or not run_anthropic_effort:
        print(
            "error: transcript lacks the run-start Anthropic model/effort receipt; "
            "refusing ambient-default synthesis",
            file=sys.stderr,
        )
        return 2

    prompt = SYNTHESIS_PROMPT.format(
        anthropic_model=_model_label(
            participant_models["opus"], run_anthropic_model
        ),
        grok_model=_model_label(participant_models["grok"], xai_adapter.DEFAULT_MODEL),
        gpt_model=_model_label(participant_models["gpt"], openai_adapter.DEFAULT_MODEL),
        coverage_summary=coverage,
        coverage_contract=contract,
        agreement_heading=agreement_heading,
        rounds_completed=rounds_completed - 1,  # rounds AFTER R1
        prereg_status="were active in rounds 3-4" if prereg_used else "were skipped",
        agent_d_status="was injected in Round 1 only" if agent_d_used else "was not used",
        round_dump=round_dump,
    )

    print(f"Synthesizing {rounds_completed} rounds ({len(round_dump)} chars)...")
    result = anthropic_adapter.call(
        prompt,
        max_tokens=anthropic_adapter.recommended_max_tokens(
            "synthesis",
            model=run_anthropic_model,
            effort=run_anthropic_effort,
        ),
        model=run_anthropic_model,
        effort=run_anthropic_effort,
    )
    if not result["ok"]:
        sys.exit(f"Synthesis failed: {result.get('error')}")

    out_path = output_dir / "META_SYNTHESIS.md"
    pricing = anthropic_adapter.pricing_for_model(result["model"])
    cost = (
        result["input_tokens"] * pricing["in"]
        + result["output_tokens"] * pricing["out"]
    ) / 1_000_000
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write("# Meta-synthesis\n\n")
        fh.write(f"Rounds completed: {rounds_completed} | "
                 f"Main-round coverage: {coverage} | "
                 f"Synthesis model: {result['model']} | "
                 f"Synthesis effort: {result.get('effort', 'unknown')} | "
                 f"Pre-reg: {'yes' if prereg_used else 'no'} | "
                 f"Agent D: {'yes' if agent_d_used else 'no'} | "
                 f"Run cost: ${total_cost:.2f} | "
                 f"Synthesis cost: ${cost:.2f}\n\n")
        fh.write("---\n\n")
        fh.write(result["text"])
    print(f"Wrote {out_path} ({result['output_tokens']} tokens, ${cost:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
