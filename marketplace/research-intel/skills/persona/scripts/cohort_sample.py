"""Sample a persona cohort from an inventory.

Four rules:
  - bucket: at least 1 per bucket, then round-robin (default)
  - random: uniform random across all entries
  - curated: caller provides explicit framework IDs
  - behavior: caller specifies one or more agent-behavior columns from a
    cohort.yaml lookup; we sample from personas scoring strong on those
    behaviors. Use when the problem calls for specific cognitive moves
    (assumption_breaker + edge_case_hunter for an audit, repairer +
    historical_memory for legacy code review, etc.)

Sampling is deterministic given the seed.
"""
from __future__ import annotations

import random
import re
from typing import Iterable


_CONF_RANK = {"HIGH": 0, "MED": 1, "MEDIUM": 1, "LOW": 2}


def _normalize_for_match(s: str) -> str:
    """Normalize a name for fuzzy matching: lowercase, strip non-alnum, collapse spaces."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def select_by_behavior(
    cohort_data: dict[str, list[dict]],
    behaviors: Iterable[str],
    min_confidence: str = "MED",
) -> list[dict]:
    """Return the union of strong-on-behavior personas, deduped, with their
    behavior-tag set attached as `_matched_behaviors`.

    cohort_data: parsed YAML — keys are behavior names, values are lists of
        {id, name, confidence, frequency} dicts.
    behaviors: which behaviors to query. Personas strong on ANY of these qualify.
    min_confidence: exclude entries below this confidence rank (HIGH=0, MED=1, LOW=2).
    """
    threshold = _CONF_RANK.get(min_confidence.upper(), 1)
    matches: dict[str, dict] = {}  # by canonical_key
    for b in behaviors:
        for entry in cohort_data.get(b, []) or []:
            if _CONF_RANK.get((entry.get("confidence") or "").upper(), 99) > threshold:
                continue
            key = entry.get("id") or _normalize_for_match(entry.get("name", ""))
            if key not in matches:
                matches[key] = {**entry, "_matched_behaviors": []}
            matches[key]["_matched_behaviors"].append(b)
    return list(matches.values())


def sample(frameworks: list[dict], n: int, rng: random.Random,
            rule: str = "bucket",
            curated_ids: list[str] | None = None,
            cohort_data: dict[str, list[dict]] | None = None,
            behaviors: list[str] | None = None,
            min_confidence: str = "MED") -> list[dict]:
    """Sample n personas per the given rule.

    frameworks: parsed inventory entries (from parse_inventory.parse)
    n: target cohort size
    rng: seeded random.Random
    rule: "bucket", "random", "curated", or "behavior"
    curated_ids: required when rule="curated" — list of framework IDs
    cohort_data: required when rule="behavior" — parsed cohort.yaml
        ({behavior_name: [{id, name, confidence, frequency}, ...], ...})
    behaviors: required when rule="behavior" — list of behavior column names
        to query in cohort_data. Personas strong on ANY of these qualify.
    min_confidence: behavior mode only — drop entries below this confidence
        rank ("HIGH" / "MED" / "LOW", default "MED")

    Returns a list of n entries (or fewer if the matched pool is smaller).
    """
    if rule == "curated":
        if not curated_ids:
            raise ValueError("curated sampling requires curated_ids")
        by_id = {f["id"]: f for f in frameworks}
        return [by_id[fid] for fid in curated_ids if fid in by_id][:n]

    if rule == "behavior":
        if not behaviors:
            raise ValueError("behavior sampling requires `behaviors`")
        if not cohort_data:
            raise ValueError("behavior sampling requires `cohort_data` (parsed cohort.yaml)")

        # 1. Pull qualifying personas from cohort.yaml
        candidates = select_by_behavior(cohort_data, behaviors, min_confidence)
        if not candidates:
            return []

        # 2. Match those canonical_keys against the inventory by normalized name.
        # Inventory IDs (e.g. "2.10") don't match cohort canonical_keys (e.g.
        # "bauhaus") — so fall back to fuzzy name match on "bauhaus" vs "Bauhaus".
        norm_to_fw = {_normalize_for_match(f["name"]): f for f in frameworks}
        matched: list[dict] = []
        for cand in candidates:
            # try exact id match (cohort IDs are normalized name strings)
            cid = cand.get("id") or ""
            cname = cand.get("name") or ""
            fw = norm_to_fw.get(_normalize_for_match(cname)) \
                or norm_to_fw.get(_normalize_for_match(cid))
            if fw is not None:
                # tag with provenance so the dispatcher can include it in analysis
                enriched = {**fw, "_matched_behaviors": cand["_matched_behaviors"]}
                matched.append(enriched)

        # 3. Deterministic shuffle, then take first n
        rng.shuffle(matched)
        return matched[:n]

    if rule == "random":
        shuffled = list(frameworks)
        rng.shuffle(shuffled)
        return shuffled[:n]

    # Default: bucket-coverage
    by_bucket: dict[str, list[dict]] = {}
    for f in frameworks:
        by_bucket.setdefault(f["group"], []).append(f)
    for entries in by_bucket.values():
        rng.shuffle(entries)
    bucket_lists = [list(v) for v in by_bucket.values() if v]
    rng.shuffle(bucket_lists)

    result: list[dict] = []
    while len(result) < n and any(bucket_lists):
        for blist in bucket_lists:
            if blist and len(result) < n:
                result.append(blist.pop())
        bucket_lists = [b for b in bucket_lists if b]
    return result[:n]
