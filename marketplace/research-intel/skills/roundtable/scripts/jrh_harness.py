#!/usr/bin/env python3
"""Item 8 — JRH judge-reliability run against /roundtable's 3 deployed jurors.

Tests the per-juror SINGLE-PASS judging operation (Round-1-style independent verdict) —
the standard JRH design and the protocol's "cheapest first probe", scoped under
eval-shipping-discipline instead of a full 5-round-x-fixture roundtable ($100s).

Jurors: the current configured roundtable defaults, resolved after setup.
4 invariance tests on a frozen 6-item fixture (3 claim + 3 pairwise) with unambiguous gold:
  1 position/order   (pairwise: swap A/B order; flip = order bias)        pass <10% flip
  2 paraphrase       (claim: reword; verdict should hold)                 pass >=80% stable
  3 verbosity        (pairwise: pad the WEAKER side; flip = length bias)  pass >=80% stay-correct
  4 stochastic       (claim: re-run N=3; agreement = noise floor)         pass >=80% consistent
Stochastic doubles as the NOISE FLOOR: bias-test flips above this floor are real bias.

Keys loaded from macOS Keychain inside-process (values never printed). Budget-capped.
Writes Judge Card + raw JSONL to OUT.
"""
import json
import os
import re
import sys
from pathlib import Path

# Adapters are imported lazily in _setup() (inside main) so that importing
# or introspecting this module NEVER spends API budget — the whole battery
# used to run at import time, which made `--help` a paid operation.
anthropic_adapter = xai_adapter = openai_adapter = None

PRICING = {  # per 1M tokens, from harness.py
    "grok": {"in": 125.0, "out": 250.0},
    "gpt":  {"in": 30.0, "out": 180.0},
}
BUDGET_USD = 20.0
# Durable, env-overridable output dir (JRH_OUT_DIR). NOT /tmp — macOS purges
# /tmp at date rollover, which would destroy the results of a paid run.
OUT = Path(os.environ.get("JRH_OUT_DIR")
           or Path.home() / "Documents" / "reports" / "security" / "jrh-results")


def _setup():
    """Side effects deferred from import time: Keychain -> env, adapter imports, OUT dir."""
    global anthropic_adapter, xai_adapter, openai_adapter
    # --- load keys from Keychain into env WITHOUT printing values ---
    # Uses the shared resolver's candidate lists rather than looking each key up
    # by its ENV-VAR name. The names diverge: OpenAI's items were renamed
    # 2026-08-04 and `OPENAI_API_KEY` no longer exists, so the previous
    # name-keyed loop had been failing the GPT juror since that date — it warned
    # to stderr and then the arm died on "OPENAI_API_KEY not set".
    sys.path.insert(0, os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "skills", "roundtable/scripts"))
    import keychain
    for line in keychain.load_keys():
        print(f"KEY: {line}", file=sys.stderr)
    absent = keychain.missing_required()
    if absent:
        sys.exit("Aborting: no credential resolved for " + ", ".join(absent)
                 + " — a missing juror invalidates the reliability run.")
    os.environ.pop("ANTHROPIC_BASE_URL", None)  # empty-string trap guard (adapters hardcode URL anyway)

    sys.path.insert(0, os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "skills", "roundtable/scripts/adapters"))
    import anthropic_adapter as _a
    import openai_adapter as _o
    import xai_adapter as _x
    anthropic_adapter, xai_adapter, openai_adapter = _a, _x, _o
    OUT.mkdir(parents=True, exist_ok=True)

JUDGE_PREAMBLE = (
    "You are an impartial technical judge. Answer with ONE line only, exactly:\n"
    "  VERDICT: <X>\n"
    "and nothing else. No reasoning, no preamble."
)

# --- FROZEN FIXTURE (gold from the user's own security-triage rule + uncontroversial facts) ---
# Claim items: gold in {SUPPORTED, REFUTED}. Ask "Is the claim TRUE? VERDICT: SUPPORTED|REFUTED"
CLAIMS = [
    {"id": "C1", "gold": "REFUTED",
     "claim": "A Rust panic triggered by malformed input is a memory-safety vulnerability "
              "(use-after-free class) and must be triaged as CVE-worthy.",
     "para":  "If untrusted input makes a Rust program panic, that panic is a memory-safety "
              "hole equivalent to a use-after-free and should be filed as a security CVE."},
    {"id": "C2", "gold": "SUPPORTED",
     "claim": "Loading a secret with os.environ.get('DB_PASSWORD', 'changeme') is a fail-open "
              "default: the service keeps running with a weak credential when the env var is unset.",
     "para":  "Using os.environ.get('DB_PASSWORD','changeme') means a missing env var silently "
              "leaves the app running on the weak fallback credential rather than crashing — a fail-open default."},
    {"id": "C3", "gold": "REFUTED",
     "claim": "Absence of any published study measuring technique X proves technique X does not work.",
     "para":  "If a literature search returns no paper that measured technique X, that absence "
              "is proof the technique is ineffective."},
]
# Pairwise items: gold = the GENUINELY more severe finding. Ask "Which is the more severe SECURITY issue? VERDICT: A|B"
PAIRS = [
    {"id": "P1", "gold_label": "more_severe",
     "A": "A hardcoded AWS secret-access-key committed in plaintext to a public git repository.",
     "B": "A log line that prints the current UTC timestamp at DEBUG level.",
     "gold_is": "A"},  # A clearly worse
    {"id": "P2", "gold_label": "more_severe",
     "A": "A README typo: 'recieve' instead of 'receive'.",
     "B": "An auth middleware that returns allow=True when the OPA policy server is unreachable (fail-open authz bypass).",
     "gold_is": "B"},  # B clearly worse
    {"id": "P3", "gold_label": "more_severe",
     "A": "SQL built by string-concatenating an unsanitized HTTP query parameter into the WHERE clause (injection).",
     "B": "A function with a 4-space vs tab indentation inconsistency.",
     "gold_is": "A"},  # A clearly worse
]
PAD = (" For completeness and to ensure full situational awareness, note that this item has been "
       "carefully documented, reviewed by multiple stakeholders, cross-referenced against industry "
       "best practices, and is provided here with extensive contextual background to aid your "
       "thorough and deliberate assessment.") * 3  # semantically-empty verbosity

cost = {"usd": 0.0}
raw = []


class JRHInvalidRun(RuntimeError):
    """A provider or verdict failure that invalidates the Judge Card."""


def ensure_runtime_receipt(model_key, result):
    """Attach a receipt without inferring context class from the model key."""
    existing = result.get("runtime_receipt")
    if isinstance(existing, dict):
        return existing

    if model_key == "opus":
        requested = result.get("requested_model") or result.get("model")
        effort = result.get("effort") or "<unavailable>"
        provider = "anthropic"
    elif model_key == "grok":
        requested = xai_adapter.DEFAULT_MODEL
        effort = "<unavailable>"
        provider = "xai"
    else:
        requested = openai_adapter.DEFAULT_MODEL
        effort = "medium"
        provider = "openai"
    context_class = result.get("context_class") or "<unavailable>"

    effective = result.get("model")
    fallback = effective != requested if effective is not None else "<unavailable>"
    receipt = {
        "requested_model": requested or "<unavailable>",
        "requested_model_source": "request_configuration",
        "effective_model": effective or "<unavailable>",
        "effective_model_source": (
            "response_metadata" if effective is not None else "unavailable"
        ),
        "provider": provider,
        "effort": effort,
        "context_class": context_class,
        "claude_code_version": "<unavailable>",
        "fallback": fallback,
        "switch_reason": (
            "provider_response_model_differs" if fallback is True else "<unavailable>"
        ),
        "refusal": False,
    }
    result["runtime_receipt"] = receipt
    return receipt


def record_raw_call(model_key, result, **fields):
    """Write one qualification event with its exact nested runtime receipt."""
    raw.append({
        **fields,
        "model": model_key,
        "runtime_receipt": result["runtime_receipt"],
    })


def judge(model_key, prompt):
    if model_key == "opus":
        r = anthropic_adapter.call(
            prompt,
            max_tokens=anthropic_adapter.recommended_max_tokens("jrh"),
        )
    elif model_key == "grok":
        r = xai_adapter.call(prompt, max_tokens=200, temperature=0.0)
    else:  # gpt — 'medium' kept for calibration parity with the recorded JUDGE_CARD baseline
           # (gpt-5.6-sol accepts 'low', smoke-verified 2026-08-19; the prior GPT pin 400'd on it).
           # 8000-tok headroom guards the empty-visible-output truncation trap (SKILL.md known constraint)
        r = openai_adapter.call(prompt, max_tokens=8000, reasoning_effort="medium")
    if not r.get("ok"):
        error_type = r.get("error_type") or "provider_failure"
        stop_reason = r.get("stop_reason") or "<unavailable>"
        raise JRHInvalidRun(
            f"{model_key} judge call failed: {error_type}; "
            f"stop_reason={stop_reason}; {r.get('error', 'unknown error')}"
        )
    receipt = ensure_runtime_receipt(model_key, r)
    if receipt.get("fallback") is True:
        raise JRHInvalidRun(
            f"{model_key} judge call used a provider model switch: "
            f"requested={receipt.get('requested_model')}, "
            f"effective={receipt.get('effective_model')}"
        )
    if r.get("ok"):
        pr = (
            anthropic_adapter.pricing_for_model(r["model"])
            if model_key == "opus"
            else PRICING[model_key]
        )
        cost["usd"] += r.get("input_tokens", 0) / 1e6 * pr["in"] + r.get("output_tokens", 0) / 1e6 * pr["out"]
        if cost["usd"] > BUDGET_USD:
            raise JRHInvalidRun(
                f"budget exceeded after {model_key} judge call: "
                f"${cost['usd']:.2f} > ${BUDGET_USD:.2f}"
            )
    return r

def parse_verdict(text, kind):
    if not text:
        return None
    m = re.search(r"VERDICT:\s*(SUPPORTED|REFUTED|A|B)", text, re.IGNORECASE)
    if m:
        v = m.group(1).upper()
        if kind == "claim" and v in ("SUPPORTED", "REFUTED"):
            return v
        if kind == "pair" and v in ("A", "B"):
            return v
    # fallback: bare token
    t = text.strip().upper()
    if kind == "claim":
        if "SUPPORTED" in t and "REFUTED" not in t:
            return "SUPPORTED"
        if "REFUTED" in t and "SUPPORTED" not in t:
            return "REFUTED"
    return None

def ask_claim(model_key, claim_text):
    p = f"{JUDGE_PREAMBLE}\n\nIs the following claim TRUE (well-supported) or FALSE?\n" \
        f"Reply VERDICT: SUPPORTED if true, VERDICT: REFUTED if false.\n\nCLAIM: {claim_text}"
    r = judge(model_key, p)
    verdict = parse_verdict(r.get("text", ""), "claim")
    if verdict is None:
        raise JRHInvalidRun(f"{model_key} returned an unparseable claim verdict")
    return verdict, r

def ask_pair(model_key, first_label, first_text, second_label, second_text):
    # first_label/second_label are the on-screen labels (A/B) in presentation order
    p = f"{JUDGE_PREAMBLE}\n\nTwo findings are below. Which is the MORE SEVERE security issue?\n" \
        f"Reply VERDICT: A or VERDICT: B (the label of the more severe one).\n\n" \
        f"{first_label}: {first_text}\n\n{second_label}: {second_text}"
    r = judge(model_key, p)
    verdict = parse_verdict(r.get("text", ""), "pair")
    if verdict is None:
        raise JRHInvalidRun(f"{model_key} returned an unparseable pair verdict")
    return verdict, r

def _models():
    """Resolve the deployed jury only after adapters and runtime env are loaded."""
    return [
        ("opus", anthropic_adapter.resolve_model()),
        ("grok", xai_adapter.DEFAULT_MODEL),
        ("gpt", openai_adapter.DEFAULT_MODEL),
    ]

def budget_ok():
    return cost["usd"] < BUDGET_USD

def main():
    """Run the full 4-test judge battery. Paid API calls happen ONLY here."""
    if OUT.exists() and not OUT.is_dir():
        raise JRHInvalidRun(f"JRH output path is not a directory: {OUT}")
    if OUT.exists() and any(OUT.iterdir()):
        raise JRHInvalidRun(
            f"JRH output directory is not empty: {OUT}; choose a fresh "
            "JRH_OUT_DIR so a failed run cannot leave a stale Judge Card"
        )
    _setup()
    models = _models()

    # ---------------- TEST 1: position/order invariance (pairwise) ----------------
    # Present A-then-B and B-then-A. The CONTENT-correct answer maps to whichever label holds gold_is.
    # flip = the model's chosen *content* differs between the two orders.
    pos_results = []  # (model, item, order1_choice_content, order2_choice_content, flipped)
    for mk, _ in models:
        for it in PAIRS:
            if not budget_ok():
                break
            # order 1: A=item.A, B=item.B
            v1, r1 = ask_pair(mk, "A", it["A"], "B", it["B"])
            record_raw_call(
                mk, r1, test="position", item=it["id"], order="AB", verdict=v1
            )
            # order 2: A=item.B, B=item.A  (labels swapped)
            v2, r2 = ask_pair(mk, "A", it["B"], "B", it["A"])
            record_raw_call(
                mk, r2, test="position", item=it["id"], order="BA", verdict=v2
            )
            # map label-choice -> which CONTENT (it.A or it.B) was chosen
            c1 = {"A": "A", "B": "B"}.get(v1)            # order1 label==content
            c2 = {"A": "B", "B": "A"}.get(v2)            # order2 labels swapped -> invert
            flipped = (c1 is not None and c2 is not None and c1 != c2)
            # correctness: did it pick gold content in each order?
            pos_results.append({"model": mk, "item": it["id"], "o1_content": c1, "o2_content": c2,
                                "flipped": flipped, "gold": it["gold_is"],
                                "o1_correct": c1 == it["gold_is"], "o2_correct": c2 == it["gold_is"]})

    # ---------------- TEST 2: paraphrase invariance (claim) ----------------
    para_results = []
    for mk, _ in models:
        for it in CLAIMS:
            if not budget_ok():
                break
            v_orig, r_orig = ask_claim(mk, it["claim"])
            v_para, r_para = ask_claim(mk, it["para"])
            record_raw_call(
                mk, r_orig, test="paraphrase", item=it["id"],
                variant="original", verdict=v_orig,
            )
            record_raw_call(
                mk, r_para, test="paraphrase", item=it["id"],
                variant="paraphrase", verdict=v_para,
            )
            para_results.append({"model": mk, "item": it["id"], "orig": v_orig, "para": v_para,
                                 "stable": (v_orig is not None and v_orig == v_para),
                                 "orig_correct": v_orig == it["gold"], "gold": it["gold"]})

    # ---------------- TEST 3: verbosity bias (pairwise; pad the WEAKER side) ----------------
    verb_results = []
    for mk, _ in models:
        for it in PAIRS:
            if not budget_ok():
                break
            weaker = "B" if it["gold_is"] == "A" else "A"
            a_text = it["A"] + (PAD if weaker == "A" else "")
            b_text = it["B"] + (PAD if weaker == "B" else "")
            v, result = ask_pair(mk, "A", a_text, "B", b_text)
            record_raw_call(
                mk, result, test="verbosity", item=it["id"],
                padded_weaker=weaker, verdict=v,
            )
            stay_correct = (v == it["gold_is"])  # still picked the genuinely-severe one despite padding the weak one
            verb_results.append({"model": mk, "item": it["id"], "verdict": v, "gold": it["gold_is"],
                                "padded": weaker, "stay_correct": stay_correct})

    # ---------------- TEST 4: stochastic stability (claim, N=3) -> noise floor ----------------
    stoch_results = []
    for mk, _ in models:
        for it in CLAIMS:
            if not budget_ok():
                break
            vs = []
            for run_number in range(1, 4):
                v, result = ask_claim(mk, it["claim"])
                vs.append(v)
                record_raw_call(
                    mk, result, test="stochastic", item=it["id"],
                    run=run_number, verdict=v,
                )
            consistent = (len([x for x in vs if x is not None]) == 3 and len(set(vs)) == 1)
            stoch_results.append({"model": mk, "item": it["id"], "runs": vs, "consistent": consistent})

    # ---------------- aggregate Judge Card ----------------
    def rate(rows, key):
        rows = [r for r in rows if r.get(key) is not None]
        if not rows:
            return (0, 0, 0.0)
        n = len(rows)
        p = sum(1 for r in rows if r[key])
        return (p, n, p / n * 100)

    card = {}
    # noise floor first (per model) from stochastic
    for mk, mname in models:
        s_p, s_n, s_rate = rate([r for r in stoch_results if r["model"] == mk], "consistent")
        pos_rows = [r for r in pos_results if r["model"] == mk]
        pos_flip_p = sum(1 for r in pos_rows if r["flipped"])
        pos_flip_n = len(pos_rows)
        pos_flip_rate = (pos_flip_p / pos_flip_n * 100) if pos_flip_n else 0.0
        pos_corr_p, pos_corr_n, _ = rate([{"c": r["o1_correct"] and r["o2_correct"]} for r in pos_rows], "c")
        par_p, par_n, par_rate = rate([r for r in para_results if r["model"] == mk], "stable")
        vrb_p, vrb_n, vrb_rate = rate([r for r in verb_results if r["model"] == mk], "stay_correct")
        card[mk] = {
            "model": mname,
            "stochastic_consistent": f"{s_p}/{s_n} ({s_rate:.0f}%)",
            "position_flip": f"{pos_flip_p}/{pos_flip_n} ({pos_flip_rate:.0f}%)",
            "position_correct_both_orders": f"{pos_corr_p}/{pos_corr_n}",
            "paraphrase_stable": f"{par_p}/{par_n} ({par_rate:.0f}%)",
            "verbosity_stay_correct": f"{vrb_p}/{vrb_n} ({vrb_rate:.0f}%)",
        }

    summary = {
        "cost_usd": round(cost["usd"], 4),
        "budget_usd": BUDGET_USD,
        "models": [m[1] for m in models],
        "fixture": {"claims": len(CLAIMS), "pairs": len(PAIRS)},
        "judge_card": card,
    }
    (OUT / "raw.jsonl").write_text("\n".join(json.dumps(r) for r in raw) + "\n", encoding="utf-8")
    (OUT / "judge_card.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("=" * 78)
    print("ITEM 8 — JRH Judge Card (single-pass per-juror reliability)")
    print("=" * 78)
    print(f"models: {', '.join(s for s in summary['models'])}")
    print(f"fixture: {len(CLAIMS)} claim + {len(PAIRS)} pairwise items   cost: ${summary['cost_usd']:.2f} / ${BUDGET_USD:.0f} budget")
    print()
    hdr = f"{'juror':<28}{'stoch(floor)':<16}{'pos-flip':<14}{'pos-correct':<14}{'parap-stable':<16}{'verb-correct':<14}"
    print(hdr)
    print("-" * len(hdr))
    for mk, _ in models:
        c = card[mk]
        print(f"{c['model']:<28}{c['stochastic_consistent']:<16}{c['position_flip']:<14}{c['position_correct_both_orders']:<14}{c['paraphrase_stable']:<16}{c['verbosity_stay_correct']:<14}")
    print()
    print("gates: pos-flip <10% PASS | parap-stable >=80% PASS | verb-correct >=80% PASS | stoch >=80% PASS")
    print(f"raw -> {OUT/'raw.jsonl'}   card -> {OUT/'judge_card.json'}")


def cli():
    """Run the paid battery with a typed nonzero invalid-run outcome."""
    try:
        main()
    except JRHInvalidRun as exc:
        print(f"JRH INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    # --help must never cost money: short-circuit before any setup/API work.
    if any(a in ('-h', '--help') for a in sys.argv[1:]):
        print(__doc__)
        print(f'Output dir: {OUT}  (override with JRH_OUT_DIR)')
        print(f'Budget cap: ${BUDGET_USD:.0f}')
        sys.exit(0)
    sys.exit(cli())
