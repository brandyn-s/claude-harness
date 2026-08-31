"""Embedding-based convergence detection using Voyage AI.

After each round, compute cosine similarity between current and prior
main outputs per agent. Auto-stop when:
  - all agents have similarity >= threshold to their own prior round
  - AND at least min_rounds completed (default 3)

If VOYAGE_API_KEY not set, returns None for similarities and the
harness falls back to fixed max_rounds.
"""
import json
import os
import urllib.request
import urllib.error
from typing import Sequence


def voyage_embed(texts: Sequence[str], model: str = "voyage-3-large",
                 input_type: str = "document") -> list[list[float]] | None:
    """Embed up to 128 texts via Voyage AI. Returns None on no key/failure."""
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        return None

    payload = {
        "input": list(texts),
        "model": model,
        "input_type": input_type,
    }
    req = urllib.request.Request(
        "https://api.voyageai.com/v1/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [item["embedding"] for item in data["data"]]
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        # Convergence detection is best-effort
        print(f"[embed] Voyage call failed: {e}; convergence check disabled")
        return None


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def round_convergence(prior_outputs: dict[str, str],
                      current_outputs: dict[str, str]) -> dict[str, float] | None:
    """Compute per-agent cosine similarity between current and prior round.

    Returns dict {agent: cosine_similarity}, or None if embedding unavailable.
    """
    if not prior_outputs or not current_outputs:
        return None
    agents = sorted(set(prior_outputs.keys()) & set(current_outputs.keys()))
    if not agents:
        return None
    texts = []
    for a in agents:
        texts.append(prior_outputs[a])
        texts.append(current_outputs[a])
    embeddings = voyage_embed(texts)
    if embeddings is None:
        return None
    sims = {}
    for i, a in enumerate(agents):
        prior_emb = embeddings[2 * i]
        curr_emb = embeddings[2 * i + 1]
        sims[a] = round(cosine(prior_emb, curr_emb), 3)
    return sims


def should_stop(round_num: int, min_rounds: int, threshold: float,
                sims: dict[str, float] | None, min_agents: int = 2) -> tuple[bool, str]:
    """Decide whether to auto-stop based on convergence.

    A stop signals "the roundtable reached a decorrelated multi-vendor
    consensus" — which is only meaningful with a quorum. ``sims`` must carry at
    least ``min_agents`` distinct vendors; otherwise the run has collapsed to a
    sub-quorum of survivors (the others errored / lost their key and dropped out
    of ``sims`` upstream) and "all agents converged" would be ONE vendor agreeing
    with its own prior round — false consensus. See harness/PROBLEM.md.
    """
    if round_num < min_rounds:
        return False, f"below min_rounds ({round_num} < {min_rounds})"
    if sims is None:
        return False, "no embedding data; using fixed max_rounds"
    if len(sims) < min_agents:
        return False, (f"below quorum: {len(sims)} vendor(s) reported, need "
                       f">={min_agents} distinct vendors for a decorrelated "
                       f"consensus (roundtable collapsed to a sub-quorum; sims={sims})")
    below = [a for a, s in sims.items() if s < threshold]
    if below:
        return False, f"agents not converged: {below} (sims={sims})"
    return True, f"all agents converged (sims={sims})"
