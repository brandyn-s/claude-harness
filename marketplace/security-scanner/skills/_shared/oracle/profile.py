"""Layer profiles — the corrected framework's replacement for the
monotonic Tier ladder.

The cascade's four layers are NOT a ladder: Layers A and D are both
"Tier 2" (mechanical) yet sit at opposite ends of the cascade — proof
that a single ordinal can't characterize a verifier. Instead each layer
carries a profile vector — soundness, false-positive rate, false-negative
rate, cost ratio, automation, and groundedness — and these do not
co-vary. The legacy "Tier N" label is retained only as a DERIVED,
deprecated descriptor (``derived_tier``), computed from groundedness, so
existing prose/references keep resolving.

Values are sourced from SPEC.md's per-layer Calibration / Cost-asymmetry
prose. Unmeasured cells are None (honest: Layer B has no calibration) —
per Principle 4, an oracle with an unmeasured failure distribution is not
ready for autonomous use, and None makes that visible rather than
papering over it with a fabricated number.
"""
from __future__ import annotations

import dataclasses
import json


@dataclasses.dataclass(frozen=True)
class LayerProfile:
    layer: str            # "A" | "B" | "C" | "D"
    name: str             # module name, e.g. "reverify"
    soundness: float | None      # P(verdict correct when it disagrees); None = unmeasured
    fp_rate: float | None        # false-positive rate bound; None = unmeasured
    fn_rate: float | None        # false-negative rate bound; None = unmeasured
    cost_ratio: str              # verification cost vs generation (prose ratio)
    automation: str              # "automated" | "human-curated"
    groundedness: str            # "mechanical" | "soft" | "curated"
    note: str = ""

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["derived_tier"] = derived_tier(self)
        return d


# groundedness → legacy tier label. This is the ONLY place the ladder is
# reconstructed; it is derived, not authoritative.
_TIER_BY_GROUNDEDNESS = {
    "mechanical": "Tier 2",
    "soft": "Tier 3",
    "curated": "Tier 4",
}


def derived_tier(p: "LayerProfile") -> str:
    """The deprecated legacy 'Tier N' label, derived from groundedness.
    Kept only for back-compat with prose/refs that still cite tiers."""
    return _TIER_BY_GROUNDEDNESS.get(p.groundedness, "Tier ?")


PROFILES: dict[str, LayerProfile] = {
    "A": LayerProfile(
        layer="A", name="reverify",
        soundness=0.95, fp_rate=0.20, fn_rate=0.05,
        cost_ratio="10-100x cheaper than generation",
        automation="automated", groundedness="mechanical",
        note=("deterministic predicate on the live tree; TPR>=0.95 / TNR>=0.80 "
              "floors. fn_rate is the structural risk — a too-narrow predicate "
              "returns STALE on a real bug."),
    ),
    "B": LayerProfile(
        layer="B", name="ensemble",
        soundness=None, fp_rate=None, fn_rate=None,
        cost_ratio="~3x MORE expensive than generation (N=3)",
        automation="automated", groundedness="soft",
        note=("N-agent LLM ensemble; NOT decorrelated from the proposer "
              "(Kim et al. ICML 2025). Uncalibrated by design — None marks the "
              "unmeasured failure distribution."),
    ),
    "C": LayerProfile(
        layer="C", name="corpus",
        soundness=1.0, fp_rate=0.0, fn_rate=0.0,
        cost_ratio="~free static check vs a live agent audit",
        automation="human-curated", groundedness="curated",
        note=("human-curated required/forbidden codes; IS ground truth for the "
              "fixture, so soundness/fp/fn are definitional on the fixture, not "
              "generalization claims."),
    ),
    "D": LayerProfile(
        layer="D", name="fix_loop",
        soundness=0.95, fp_rate=0.20, fn_rate=0.05,
        cost_ratio="5-30x cheaper than the fix attempt",
        automation="automated", groundedness="mechanical",
        note=("shares Reproducer.fires() with Layer A, adding the temporal "
              "pre/post-fix dimension."),
    ),
}


def render_profiles(fmt: str = "markdown") -> str:
    """Render the four layer profiles as a markdown table or a JSON list."""
    rows = [PROFILES[k] for k in ("A", "B", "C", "D")]
    if fmt == "json":
        return json.dumps([p.as_dict() for p in rows], indent=2) + "\n"

    def cell(x) -> str:
        if x is None:
            return "—"
        return f"{x:.2f}" if isinstance(x, float) else str(x)

    out = [
        "| Layer | Name | Soundness | FP rate | FN rate | Cost ratio | Automation | Groundedness | Derived tier |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in rows:
        out.append(
            f"| {p.layer} | `{p.name}` | {cell(p.soundness)} | {cell(p.fp_rate)} | "
            f"{cell(p.fn_rate)} | {p.cost_ratio} | {p.automation} | {p.groundedness} | "
            f"{derived_tier(p)} |"
        )
    return "\n".join(out) + "\n"
