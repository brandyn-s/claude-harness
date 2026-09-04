"""contracts/model-capabilities.json is the source of record for per-model API behaviour.

Two gates: the block rendered into skills/api-guardrails/SKILL.md must match the
contract byte-for-byte (so the document cannot drift), and `verified_on` must be
younger than 120 days (so the facts cannot silently age).

Run: pytest bin/test_render_model_capabilities.py -q
"""
from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime, timedelta

from scripts import model_contracts

REPO = model_contracts.ROOT
STALE_AFTER_DAYS = 120


def _load():
    spec = importlib.util.spec_from_file_location(
        "render_model_capabilities", REPO / "bin" / "render-model-capabilities.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_block_matches_contract_byte_for_byte():
    renderer = _load()
    text = renderer.SKILL.read_text(encoding="utf-8")
    assert renderer.current_block(text) == renderer.render_block(renderer.load_contract()), (
        "skills/api-guardrails/SKILL.md capability table drifted from "
        "contracts/model-capabilities.json; run bin/render-model-capabilities.py --write"
    )


def test_check_mode_reports_the_skill_current_and_a_tampered_copy_stale(tmp_path, monkeypatch, capsys):
    renderer = _load()
    assert renderer.main(["--check"]) == 0

    # Known-positive control: one changed cell in the block must fail --check.
    tampered = tmp_path / "SKILL.md"
    text = renderer.SKILL.read_text(encoding="utf-8")
    block = renderer.current_block(text)
    tampered.write_text(text.replace(block, block.replace("returns 400", "is accepted", 1)), encoding="utf-8")
    monkeypatch.setattr(renderer, "SKILL", tampered)
    assert renderer.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().err

    assert renderer.main(["--write"]) == 0
    assert renderer.current_block(tampered.read_text(encoding="utf-8")) == block


def test_render_reads_every_current_row_and_no_superseded_one():
    renderer = _load()
    block = renderer.render_block(renderer.load_contract())
    for model in model_contracts.current_models():
        assert f"(`{model['id']}`)" in block
    for model_id in model_contracts.superseded_ids():
        assert model_id not in block, "superseded models are frozen evidence, not current guidance"


def test_render_encodes_the_disable_effort_cap_and_absent_effort():
    renderer = _load()
    contract = renderer.load_contract()
    capped = next(m for m in contract["models"] if m["thinking"]["disable"]["max_effort"])
    no_effort = next(m for m in contract["models"] if not m["effort"]["levels"])
    block = renderer.render_block(contract)
    cap = capped["thinking"]["disable"]["max_effort"]
    above = contract["effort_levels"][contract["effort_levels"].index(cap) + 1:]
    assert f"through `{cap}`; disabled + " + "/".join(f"`{x}`" for x in above) + " returns 400." in block
    assert "Effort is unavailable." in block
    assert no_effort["display_name"] in block


def test_contract_shape_is_complete():
    contract = model_contracts.capabilities()
    assert contract["schemaVersion"] == 1
    assert contract["source"] and "verified_on" in contract["source"]
    levels = contract["effort_levels"]
    required = {
        "id", "display_name", "tier", "thinking", "effort", "sampling", "assistant_prefill",
        "retention", "refusals", "priority_tier", "web_fetch", "availability",
        "context_window_tokens", "max_output_tokens", "notes",
    }
    ids = []
    for model in contract["models"]:
        assert required <= model.keys(), model["id"]
        assert model["thinking"]["adaptive"] in {"always_on", "default_on", "default_off", "unsupported"}
        cap = model["thinking"]["disable"]["max_effort"]
        assert cap is None or cap in levels
        assert set(model["effort"]["levels"]) <= set(levels)
        assert model["sampling"] in {"rejected", "temperature_or_top_p"}
        assert model["refusals"] in {None, "classifier", "cyber_safeguards", "none"}
        assert model["availability"] in {"general", "project-glasswing"}
        ids.append(model["id"])
    for model in contract["superseded"]:
        assert {"id", "display_name", "tier", "superseded_by", "thinking", "sampling",
                "assistant_prefill"} <= model.keys(), model["id"]
        ids.append(model["id"])
    assert len(ids) == len(set(ids)), "duplicate model id in the contract"
    assert set(model_contracts.covered_ids()) == {
        m["id"] for m in contract["models"] if m["retention"]["covered_model"]
    }
    # every tier resolves to exactly one current row
    for tier in {m["tier"] for m in contract["models"]}:
        assert model_contracts.model_id(tier)


def _days_old(verified_on: str, today: date | None = None) -> int:
    return ((today or datetime.now(tz=UTC).date()) - date.fromisoformat(verified_on)).days


def _staleness_failure(verified_on: str, age: int) -> str | None:
    """The gate: None while fresh, otherwise the message telling the maintainer what to redo."""
    if age <= STALE_AFTER_DAYS:
        return None
    return (
        f"contracts/model-capabilities.json verified_on {verified_on} is {age} days old "
        f"(limit {STALE_AFTER_DAYS}). Re-verify every row against the primary sources listed in "
        "skills/api-guardrails/SKILL.md: thinking modes and the disable/effort cap, effort levels, "
        "sampling and prefill restrictions, retention class, refusal behaviour, Priority Tier and "
        "web fetch availability, Haiku context/output limits, and the superseded rows' restrictions. "
        "Then set verified_on to the verification date and run "
        "bin/render-model-capabilities.py --write."
    )


def test_verified_on_is_younger_than_120_days():
    contract = model_contracts.capabilities()
    failure = _staleness_failure(contract["verified_on"], _days_old(contract["verified_on"]))
    assert failure is None, failure


def test_staleness_gate_fires_on_an_old_date():
    """Known-positive control for the gate above."""
    aged = (datetime.now(tz=UTC).date() - timedelta(days=STALE_AFTER_DAYS + 1)).isoformat()
    failure = _staleness_failure(aged, _days_old(aged))
    assert failure is not None
    assert "Re-verify every row" in failure and "render-model-capabilities.py --write" in failure
    fresh = datetime.now(tz=UTC).date().isoformat()
    assert _staleness_failure(fresh, _days_old(fresh)) is None
    assert _days_old("2026-01-01", today=date(2026, 1, 31)) == 30
