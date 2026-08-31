"""Layer B — in-process CROSS-VENDOR dispatch (opt-in, never in CI).

Today Layer B is orchestrator-driven and defaults to same-vendor agents —
the weakest decorrelation (SPEC §"Layer B"). This module upgrades it: it
calls the roundtable anthropic/openai/xai adapters in-process so the N
agents are genuinely different model FAMILIES, parses each vendor's
findings, and feeds ``ensemble.aggregate``. It records per-vendor
``model_version`` in the trace (the first code to write ``layer:"B"``
records) and tags each ConsensusFinding with the distinct vendors that
reported it.

This does NOT make Layer B a sound oracle — cross-vendor LLM judges still
co-err (Kim et al. ICML 2025); see SPEC §"Layer B". It buys *more*
decorrelation than same-vendor N-of-1, nothing categorical.

Opt-in and key-graceful: missing API keys are recorded as unavailable
vendors, never fatal, so this can run with 0-3 keys present. It is never
invoked by the calibration suite or CI — only via
``audit-skill-oracle.py ensemble-dispatch``.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from .ensemble import aggregate, ConsensusFinding  # noqa: F401
from .finding import Finding
from .trace import finding_id, trace_invocation


# Default vendor order. Each maps to a roundtable adapter file exposing
# `call(prompt, max_tokens=..., model=None) -> {"ok": bool, "text", "model", ...}`.
VENDORS = ("anthropic", "openai", "xai")
_ADAPTER_FILES = {
    "anthropic": "anthropic_adapter.py",
    "openai": "openai_adapter.py",
    "xai": "xai_adapter.py",
}


def _adapters_dir() -> Path:
    # ensemble_dispatch.py is skills/_shared/oracle/ ; adapters live at
    # skills/roundtable/scripts/adapters/.
    return Path(__file__).resolve().parents[2] / "roundtable" / "scripts" / "adapters"


def _load_adapter(vendor: str):
    """Load one adapter module by path and return its `call` function. The
    adapter self-inserts its own dir for `from common import ...`, but we
    also add it so the import resolves regardless of load order."""
    d = _adapters_dir()
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    fpath = d / _ADAPTER_FILES[vendor]
    spec = importlib.util.spec_from_file_location(f"oracle_adapter_{vendor}", fpath)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load adapter for {vendor} at {fpath}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.call


def load_default_adapters() -> dict:
    """Return {vendor: call_fn} for every adapter that imports cleanly.
    Adapters that fail to import (missing file) are simply omitted and
    recorded downstream as unavailable."""
    out: dict = {}
    for v in VENDORS:
        try:
            out[v] = _load_adapter(v)
        except Exception:
            continue
    return out


def parse_findings_from_text(text: str, skill: str) -> list[Finding]:
    """Extract the first JSON array of findings from a vendor's free-text
    response (fenced ```json block preferred, else the first bracketed
    span) and parse each into a Finding. Returns [] on no/invalid JSON —
    a vendor that didn't emit a well-formed findings array contributes
    nothing to the ensemble rather than crashing it."""
    if not text:
        return []
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    blob = m.group(1) if m else None
    if blob is None:
        i, j = text.find("["), text.rfind("]")
        blob = text[i:j + 1] if (i != -1 and j > i) else None
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[Finding] = []
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            entry.setdefault("skill", skill)
            try:
                out.append(Finding.from_dict(dict(entry)))
            except Exception:
                continue
    return out


def _trace_b(skill: str, vendor: str, res: dict) -> None:
    """Write one Layer-B per-vendor dispatch trace record. model_version
    carries the vendor's reported model id (SPEC §"Trace contract")."""
    fid = finding_id(skill, "ensemble-dispatch", vendor)
    ok = bool(res.get("ok"))
    with trace_invocation("B", skill, fid,
                          {"vendor": vendor, "ok": ok},
                          model_version=res.get("model", vendor)) as tr:
        tr["verdict"] = "DISPATCHED" if ok else "VENDOR_UNAVAILABLE"
        tr["evidence"] = (res.get("error") or f"{len(res.get('text', ''))} chars")[:200]


def dispatch_cross_vendor(prompt: str, skill: str, vendors=None,
                          adapters=None, max_tokens: int = 4000,
                          trace: bool = True) -> list[tuple[str, dict]]:
    """Call each vendor's adapter; return [(vendor, result_dict)]. Records
    absent vendors as {"ok": False} without raising. ``adapters`` may be
    injected (tests pass mock callables); defaults to the real adapters."""
    vendors = list(vendors) if vendors else list(VENDORS)
    adapters = adapters if adapters is not None else load_default_adapters()
    results: list[tuple[str, dict]] = []
    for v in vendors:
        fn = adapters.get(v)
        if fn is None:
            res = {"ok": False, "error": f"adapter for {v!r} unavailable (no key / import failed)"}
        else:
            try:
                res = fn(prompt, max_tokens=max_tokens)
            except Exception as e:
                res = {"ok": False, "error": f"adapter raised: {type(e).__name__}: {e}"}
        results.append((v, res))
        if trace:
            try:
                _trace_b(skill, v, res)
            except Exception:
                pass  # trace write is best-effort; never break dispatch
    return results


def ensemble_cross_vendor(prompt: str, skill: str, vendors=None,
                          adapters=None, min_agreement=None):
    """Dispatch cross-vendor, parse each vendor's findings, aggregate.
    Returns (consensus, vendors_used) where vendors_used are the vendors
    that returned ok=True. The ConsensusFindings carry the distinct
    vendors that reported each one (real decorrelation provenance)."""
    results = dispatch_cross_vendor(prompt, skill, vendors=vendors, adapters=adapters)
    agent_findings: list[list[Finding]] = []
    vendor_by_agent: list[str] = []
    vendors_used: list[str] = []
    for v, res in results:
        if not res.get("ok"):
            continue
        agent_findings.append(parse_findings_from_text(res.get("text", ""), skill))
        vendor_by_agent.append(v)
        vendors_used.append(v)
    consensus = aggregate(agent_findings, min_agreement=min_agreement,
                          vendor_by_agent=vendor_by_agent)
    return consensus, vendors_used
