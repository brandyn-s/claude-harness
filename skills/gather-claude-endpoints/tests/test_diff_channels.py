"""Prove the drift detector before trusting its output.

Per verify-effectiveness.md: a measurement instrument gets validated against a
tiny fixture with hand-verifiable ground truth BEFORE it is pointed at real
targets. These tests are that fixture. They assert FP=0 / FN=0 on a corpus
small enough to count by hand, and they mutation-check that each verdict class
is actually reachable (a detector that can never report REMOVED is useless).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diff_channels as dc  # noqa: E402 -- resolves via the sys.path insert above
from channel_specs import BY_KEY, Extractor  # noqa: E402 -- resolves via the sys.path insert above

# --------------------------------------------------------------------------
# Ground-truth fixture: 6 event names, 3 env vars. Countable by hand.
# --------------------------------------------------------------------------
# Declaration forms mirror the LIVE page (measured 2026-08-22): metrics are
# table first-cells, events carry the `**Event Name**:` marker, trace spans are
# bold-backtick headings in the traces (beta) section. The old fixture used
# bare backticked tokens for events, which is the pattern that filed 4 SPAN
# names as events on the real page.
FIXTURE_OTEL = """
# Monitoring
export CLAUDE_CODE_ENABLE_TELEMETRY=1

| `claude_code.session.count` | Count of CLI sessions | none |
| `claude_code.token.usage` | Tokens | tokens |

#### User prompt event
**Event Name**: `claude_code.user_prompt`
#### Tool result event
**Event Name**: `claude_code.tool_result`
#### Compaction event
**Event Name**: `claude_code.compaction`
#### Skill activated event
**Event Name**: `claude_code.skill_activated`

Optionally export distributed traces via the [traces protocol](#traces-beta).

**`claude_code.tool`**

**`claude_code.tool.execution`**

| `OTEL_METRICS_EXPORTER` | ... |
| `OTEL_LOG_USER_PROMPTS` | ... |
| `CLAUDE_CODE_OTEL_CONTENT_MAX_LENGTH` | ... |
"""

# Events, metrics, and trace spans are PAIRWISE-DISJOINT fact-sets by design:
# keeping them separate means one rename cannot show up as simultaneous drift
# in two sets, which would double-count the change — and a span cannot be
# filed as an event (the 30-vs-26 baseline contamination fixed 2026-08-22).
EXPECTED_EVENTS = sorted(
    [
        "claude_code.user_prompt",
        "claude_code.tool_result",
        "claude_code.compaction",
        "claude_code.skill_activated",
    ]
)
EXPECTED_METRICS = sorted(["claude_code.session.count", "claude_code.token.usage"])
EXPECTED_SPANS = sorted(["claude_code.tool", "claude_code.tool.execution"])
EXPECTED_ENVS = sorted(
    [
        "OTEL_METRICS_EXPORTER",
        "OTEL_LOG_USER_PROMPTS",
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "CLAUDE_CODE_OTEL_CONTENT_MAX_LENGTH",
    ]
)


def _ex(key: str) -> Extractor:
    for c in BY_KEY.values():
        for e in c.extractors:
            if e.key == key:
                return e
    raise AssertionError(f"no extractor {key}")


def _relaxed(key: str, minimum: int = 1) -> Extractor:
    """Same pattern, lowered floor -- so a 9-line fixture isn't INSTRUMENT_BLIND."""
    e = _ex(key)
    return Extractor(e.key, e.pattern, minimum, e.kind, e.note)


# ---------------------------- extraction is exact ----------------------------


def test_events_extracted_exactly_no_fp_no_fn():
    res = dc.extract(FIXTURE_OTEL, _relaxed("otel-events"))
    assert res.verdict == dc.CLEAN
    assert res.values == EXPECTED_EVENTS, "false positives or misses in event extraction"


def test_metrics_events_and_spans_are_pairwise_disjoint_fact_sets():
    """No set may leak into another, or one rename double-counts as two drifts.
    Spans are the set that DID leak before 2026-08-22: the events pattern
    captured any single-segment token, filing claude_code.{tool,hook,
    llm_request,interaction} as events (baseline said 30 'all documented';
    the observed inventory held 26 — the 4 unobserved were exactly the spans)."""
    metrics = dc.extract(FIXTURE_OTEL, _relaxed("otel-metrics"))
    events = dc.extract(FIXTURE_OTEL, _relaxed("otel-events"))
    spans = dc.extract(FIXTURE_OTEL, _relaxed("otel-trace-spans"))
    assert metrics.values == EXPECTED_METRICS
    assert events.values == EXPECTED_EVENTS
    assert spans.values == EXPECTED_SPANS
    assert not set(metrics.values) & set(events.values)
    assert not set(metrics.values) & set(spans.values)
    assert not set(events.values) & set(spans.values)
    # The single-segment span name must NOT be captured as an event.
    assert "claude_code.tool" not in events.values


def test_env_vars_extracted_exactly():
    res = dc.extract(FIXTURE_OTEL, _relaxed("otel-env-vars"))
    assert res.values == EXPECTED_ENVS


def test_activity_type_pattern_matches_described_enum_bullets_only():
    # The declaration form is an enum bullet FOLLOWED BY a description
    # paragraph. Measured 2026-08-22 on the live 2.36 MB reference:
    # verb-suffix matching missed real types (`seat_tiers_purchased`,
    # `inference_hooks_request_denied`) and captured ~80 field/enum phantoms.
    body = (
        '  - `"claude_chat_created"`\n\n    A chat was created.\n\n'
        '  - `"seat_tiers_purchased"`\n\n    Seat tiers were purchased.\n\n'
        '  - `"inference_hooks_request_denied"`\n\n    Inference was denied.\n\n'
        # bare enum bullet with no description (actor-type form) -- NOT a type
        '  - `"api_actor"`\n\n  - `"user_actor"`\n\n'
        # per-setting discriminator (field context, not a bullet) -- NOT a type
        '    - `type: optional "chat_enabled"`\n\n'
        # prose token -- NOT a type
        "organization_id and group_member_added in prose\n"
    )
    res = dc.extract(body, _relaxed("activity-types"))
    assert "claude_chat_created" in res.values
    assert "seat_tiers_purchased" in res.values
    assert "inference_hooks_request_denied" in res.values
    assert "api_actor" not in res.values
    assert "chat_enabled" not in res.values
    assert "organization_id" not in res.values
    assert "group_member_added" not in res.values


# ------------------- below-floor is a DETECTOR bug, not removal -------------


def test_below_min_expected_reports_instrument_blind_not_removal():
    """A restructured page must never read as 'the vendor removed everything'."""
    res = dc.extract("nothing here", _ex("otel-events"))  # real floor = 25
    assert res.verdict == dc.INSTRUMENT_BLIND
    assert "min_expected" in res.detail


def test_bad_regex_reports_instrument_blind():
    res = dc.extract("x", Extractor("bad", r"([unclosed", 1))
    assert res.verdict == dc.INSTRUMENT_BLIND


# ------------------------- channel-level verdicts ---------------------------


def _fixture_dir(tmp_path: Path, body: str, key: str = "otel") -> Path:
    d = tmp_path / "fixtures"
    d.mkdir(exist_ok=True)
    (d / f"{key}.md").write_text(body, encoding="utf-8")
    return d


def test_missing_liveness_marker_reports_channel_dead(tmp_path):
    """Soft-404s return HTTP 200 with a wrong body -- status code proves nothing."""
    fx = _fixture_dir(tmp_path, "# Page not found\nSorry.")
    r = dc.process(BY_KEY["otel"], tmp_path, fx, "2026-07-27", update=False)
    assert r.verdict == dc.CHANNEL_DEAD
    assert "marker" in r.detail


def test_absent_fixture_reports_fetch_failed_not_drift(tmp_path):
    fx = tmp_path / "empty"
    fx.mkdir()
    r = dc.process(BY_KEY["otel"], tmp_path, fx, "2026-07-27", update=False)
    assert r.verdict == dc.FETCH_FAILED


def test_first_run_establishes_baseline_then_second_run_is_clean(tmp_path):
    """First run must WRITE the baseline, not defer it to 'next run'."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    spec = BY_KEY["otel"]
    # Relax floors so the tiny fixture is usable.
    relaxed = type(spec)(
        spec.key,
        spec.title,
        spec.url,
        spec.marker,
        spec.surface,
        tuple(_relaxed(e.key) for e in spec.extractors),
        spec.note,
    )

    r1 = dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)
    assert r1.verdict == dc.NO_BASELINE
    bp = dc.baseline_path(tmp_path, "otel-events")
    assert bp.exists(), "first run did not persist the baseline"
    assert json.loads(bp.read_text())["values"] == EXPECTED_EVENTS

    r2 = dc.process(relaxed, tmp_path, fx, "2026-07-27", update=False)
    assert r2.verdict == dc.CLEAN, "identical input must not report drift"


def test_addition_is_detected(tmp_path):
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    spec = BY_KEY["otel"]
    relaxed = type(spec)(
        spec.key, spec.title, spec.url, spec.marker, spec.surface,
        (_relaxed("otel-events"),), spec.note,
    )
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    grown = FIXTURE_OTEL + "\n#### Sandbox event\n**Event Name**: `claude_code.sandbox_denied`\n"
    fx2 = _fixture_dir(tmp_path, grown, key="otel")
    r = dc.process(relaxed, tmp_path, fx2, "2026-07-28", update=False)
    assert r.verdict == dc.DRIFT
    d = r.diffs["otel-events"]
    assert d["added"] == ["claude_code.sandbox_denied"]
    assert d["removed"] == []


def test_removal_is_detected(tmp_path):
    """The whole reason baselines exist: prose reading cannot see a removal."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    spec = BY_KEY["otel"]
    relaxed = type(spec)(
        spec.key, spec.title, spec.url, spec.marker, spec.surface,
        (_relaxed("otel-events"),), spec.note,
    )
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    shrunk = FIXTURE_OTEL.replace("`claude_code.compaction`", "")
    fx2 = _fixture_dir(tmp_path, shrunk, key="otel")
    r = dc.process(relaxed, tmp_path, fx2, "2026-07-28", update=False)
    assert r.verdict == dc.DRIFT
    assert r.diffs["otel-events"]["removed"] == ["claude_code.compaction"]


def test_baseline_write_is_idempotent_and_stamped(tmp_path):
    p = dc.write_baseline(tmp_path, "k", ["b", "a"], "https://x", "2026-07-27")
    data = json.loads(p.read_text())
    assert data["captured"] == "2026-07-27"
    assert data["count"] == 2
    assert data["source_url"] == "https://x"


# ------------------- provenance: observed-only hold-out ----------------------
# These pin finding #12 (2026-08-01). The differ asks ONE source (docs) but a
# baseline may hold values learned from our telemetry. Comparing those against a
# docs extraction reported them REMOVED on EVERY run -- 25 phantom rows on run 3,
# inverting the alarm on two fact-sets that back live closed-set detectors.


def _otel_events_only(spec):
    return type(spec)(
        spec.key, spec.title, spec.url, spec.marker, spec.surface,
        (_relaxed("otel-events"),), spec.note,
    )


def test_observed_only_value_is_not_reported_removed(tmp_path):
    """THE regression this fix exists for: a telemetry-learned value the docs
    never listed must NOT read as a vendor removal."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    # Simulate reconcile_observed.py merging a value only an observed inventory can see.
    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    data["values"] = sorted(data["values"] + ["claude_code.subagent_completed"])
    data["observed_values"] = ["claude_code.subagent_completed"]
    data["observed_source"] = "docs + live-observed reconciliation"
    bp.write_text(json.dumps(data, indent=2) + "\n")

    r = dc.process(relaxed, tmp_path, fx, "2026-07-28", update=False)
    d = r.diffs["otel-events"]
    assert d["removed"] == [], "observed-only value reported as a vendor REMOVAL"
    assert d["added"] == []
    assert r.verdict == dc.OBSERVED_ONLY
    assert d["observed_only_count"] == 1
    assert d["docs_baseline_count"] == len(EXPECTED_EVENTS)


def test_real_removal_still_detected_when_observed_set_present(tmp_path):
    """The hold-out must not become a blanket amnesty: a docs-sourced value that
    disappears is still DRIFT even when the baseline carries observed values."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    data["values"] = sorted(data["values"] + ["claude_code.subagent_completed"])
    data["observed_values"] = ["claude_code.subagent_completed"]
    bp.write_text(json.dumps(data, indent=2) + "\n")

    shrunk = FIXTURE_OTEL.replace("`claude_code.compaction`", "")
    fx2 = _fixture_dir(tmp_path, shrunk, key="otel")
    r = dc.process(relaxed, tmp_path, fx2, "2026-07-28", update=False)
    assert r.verdict == dc.DRIFT
    assert r.diffs["otel-events"]["removed"] == ["claude_code.compaction"]


def test_observed_value_appearing_in_docs_is_promoted_not_added(tmp_path):
    """When the vendor finally documents a value we had only observed, that is a
    state change (promotion), not an addition -- and it must LEAVE the held-out
    set, or it would be excluded from every future diff and never checked again."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    held = "claude_code.sandbox_denied"
    data["values"] = sorted(data["values"] + [held])
    data["observed_values"] = [held]
    bp.write_text(json.dumps(data, indent=2) + "\n")

    # The docs now list it (in the declaration form the extractor anchors on).
    grown = FIXTURE_OTEL + f"\n#### Sandbox\n**Event Name**: `{held}`\n"
    fx2 = _fixture_dir(tmp_path, grown, key="otel")
    r = dc.process(relaxed, tmp_path, fx2, "2026-07-28", update=True)
    d = r.diffs["otel-events"]
    assert d["added"] == [], "a promoted value is not a new vendor addition"
    assert d["removed"] == []
    assert d["promoted"] == [held]

    after = json.loads(bp.read_text())
    assert held in after["values"]
    assert held not in after.get("observed_values", []), \
        "promoted value stayed held out -- it would never be diffed again"


def test_update_baseline_preserves_observed_provenance(tmp_path):
    """The pre-fix writer emitted a fixed 5-key dict, so --update-baseline
    ERASED observed_values/observed_source -- the docs-only differ destroying
    the reconciliation record it was meant to respect."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    data["values"] = sorted(data["values"] + ["claude_code.subagent_completed"])
    data["observed_values"] = ["claude_code.subagent_completed"]
    data["observed_source"] = "docs + live-observed reconciliation"
    bp.write_text(json.dumps(data, indent=2) + "\n")

    dc.process(relaxed, tmp_path, fx, "2026-07-28", update=True)
    after = json.loads(bp.read_text())
    assert after.get("observed_values") == ["claude_code.subagent_completed"], \
        "--update-baseline erased the telemetry provenance record"
    assert after.get("observed_source")
    assert "claude_code.subagent_completed" in after["values"], \
        "--update-baseline deleted a telemetry-learned value"


def test_stale_observed_entry_does_not_invent_a_held_out_member(tmp_path):
    """An observed_values entry no longer in `values` is stale bookkeeping; it
    must not create a phantom held-out member or skew the docs count."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    data["observed_values"] = ["claude_code.never_in_values"]
    bp.write_text(json.dumps(data, indent=2) + "\n")

    r = dc.process(relaxed, tmp_path, fx, "2026-07-28", update=False)
    d = r.diffs["otel-events"]
    assert d["observed_only_count"] == 0
    assert d["docs_baseline_count"] == len(EXPECTED_EVENTS)
    assert r.verdict == dc.CLEAN


def test_observed_source_without_observed_values_stays_docs_sourced(tmp_path):
    """A flat observed_source says SOME values came from telemetry but not WHICH.
    That is deliberately treated as fully docs-sourced: a loud wrong answer beats
    a silent guess about which values to exclude from checking."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    data["observed_source"] = "docs + live-observed reconciliation"
    bp.write_text(json.dumps(data, indent=2) + "\n")

    r = dc.process(relaxed, tmp_path, fx, "2026-07-28", update=False)
    assert r.diffs["otel-events"]["observed_only_count"] == 0
    assert r.verdict == dc.CLEAN


def test_observed_only_does_not_gate_the_exit_code(tmp_path):
    """OBSERVED_ONLY is informational. If it set exit 1, every run on a
    reconciled baseline would read as drift -- the phantom problem in a new hat."""
    assert dc.OBSERVED_ONLY not in (dc.DRIFT, dc.CLEAN)
    assert dc.OBSERVED_ONLY not in (dc.FETCH_FAILED, dc.CHANNEL_DEAD, dc.INSTRUMENT_BLIND)


# --------------------------- registry sanity --------------------------------


def test_every_extractor_key_is_unique():
    keys = [e.key for c in BY_KEY.values() for e in c.extractors]
    assert len(keys) == len(set(keys)), "duplicate extractor key would clobber a baseline file"


# --------------------- coverage guard (finding #13) --------------------------
# The guard had NO tests, which is how a whole subdirectory stayed invisible for
# two runs while it reported "0 uncovered".

_IDX = """
- [Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces.md)
- [Brand New](https://platform.claude.com/docs/en/manage-claude/brand-new-page.md)
- [AWS](https://platform.claude.com/docs/en/manage-claude/wif-providers/aws.md)
- [Okta](https://platform.claude.com/docs/en/manage-claude/wif-providers/okta.md)
"""


def test_coverage_guard_sees_subdirectory_pages():
    """A page one directory deep must be enumerated. The pre-fix pattern had no
    `/`, so `wif-providers/*` (7 real pages) could not match and the guard
    answered '0 uncovered' for a reason unrelated to coverage."""
    from channel_specs import enumerate_uncovered_pages

    pages = {p for p, _ in enumerate_uncovered_pages(_IDX)}
    assert "wif-providers/aws.md" in pages, "subdirectory page invisible to the guard"
    assert "wif-providers/okta.md" in pages


def test_coverage_guard_keys_subdirectory_pages_by_relative_path():
    """Keys must not collapse to the bare filename -- that is ambiguous across
    subdirectories and could collide with a same-named top-level page."""
    from channel_specs import enumerate_uncovered_pages

    pages = {p for p, _ in enumerate_uncovered_pages(_IDX)}
    assert "aws.md" not in pages, "subdirectory page collapsed to a bare filename"


def test_coverage_guard_reports_an_unrecorded_page_as_uncovered():
    """The guard's whole purpose: a page that is neither channel nor recorded
    exclusion must surface. Negative control for the two tests above -- without
    it, a guard that returned an empty list would pass them both."""
    from channel_specs import enumerate_uncovered_pages

    rows = dict(enumerate_uncovered_pages(_IDX))
    assert rows["brand-new-page.md"].startswith("UNCOVERED")
    assert rows["workspaces.md"] == "CHANNEL"
    assert rows["wif-providers/aws.md"].startswith("EXCLUDED")


def test_every_deliberate_exclusion_has_a_reason():
    """An empty reason defeats the point -- the registry exists so each exclusion
    is a recorded decision, not an accident of keyword filtering."""
    from channel_specs import DELIBERATE_EXCLUSIONS

    blank = [k for k, v in DELIBERATE_EXCLUSIONS.items() if not (v or "").strip()]
    assert blank == [], f"exclusions with no recorded reason: {blank}"


def test_every_channel_has_a_marker_and_url():
    for c in BY_KEY.values():
        assert c.marker and c.url.startswith("https://")


def test_every_extractor_pattern_compiles_with_one_group():
    import re

    for c in BY_KEY.values():
        for e in c.extractors:
            rx = re.compile(e.pattern)
            assert rx.groups >= 1, f"{e.key} has no capture group"


# --- baseline freshness gate (run 5) --------------------------------------
# Run 5 diffed a checkout 35 commits behind origin/main and "found" three changes
# run 4 had already shipped; --update-baseline there would have reverted them.


def _fake_git(tmp_path, behind: int, fetch_rc: int = 0, is_repo: bool = True):
    """Stand in for `git -C kb ...` with a controllable behind-count."""
    calls = []

    def run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        sub = cmd[3]

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        if sub == "rev-parse":
            R.returncode = 0 if is_repo else 128
        elif sub == "fetch":
            R.returncode = fetch_rc
            R.stderr = "could not resolve host" if fetch_rc else ""
        elif sub == "rev-list":
            R.stdout = f"{behind}\n"
        elif sub == "log":
            R.stdout = "abc1234 run 4 — Inference hooks\n" if behind else ""
        return R

    return run, calls


def test_current_checkout_reports_fresh(tmp_path, monkeypatch):
    run, _ = _fake_git(tmp_path, behind=0)
    monkeypatch.setattr(dc.subprocess, "run", run)
    status, _detail = dc.baseline_freshness(tmp_path)
    assert status == "FRESH"


def test_behind_checkout_reports_stale_and_names_the_commits(tmp_path, monkeypatch):
    run, _ = _fake_git(tmp_path, behind=2)
    monkeypatch.setattr(dc.subprocess, "run", run)
    status, detail = dc.baseline_freshness(tmp_path)
    assert status == "STALE"
    assert "2 origin/main commit" in detail
    assert "Inference hooks" in detail, "a stale verdict must name what it is missing"


def test_failed_fetch_is_UNKNOWN_never_FRESH(tmp_path, monkeypatch):
    """A freshness check whose own instrument failed proves nothing. Reporting FRESH
    here is how a stale tree gets trusted."""
    run, _ = _fake_git(tmp_path, behind=0, fetch_rc=1)
    monkeypatch.setattr(dc.subprocess, "run", run)
    status, detail = dc.baseline_freshness(tmp_path)
    assert status == "UNKNOWN"
    assert "fetch failed" in detail


def test_non_git_tree_is_UNKNOWN(tmp_path, monkeypatch):
    run, _ = _fake_git(tmp_path, behind=0, is_repo=False)
    monkeypatch.setattr(dc.subprocess, "run", run)
    assert dc.baseline_freshness(tmp_path)[0] == "UNKNOWN"


def test_offline_fixture_runs_skip_the_freshness_gate(tmp_path, monkeypatch):
    """--offline reads fixtures, not the KB's live baselines, so gating it would
    break the test suite this gate is supposed to protect."""
    called = []
    monkeypatch.setattr(dc, "baseline_freshness",
                        lambda kb: called.append(kb) or ("STALE", "x"))
    monkeypatch.setattr(sys, "argv",
                        ["diff_channels.py", "--kb", str(tmp_path),
                         "--offline", str(tmp_path), "--channel", "otel"])
    dc.main()
    assert called == [], "offline run must not consult git freshness"


# --- prose Watching triggers (run 6) ----------------------------------------
# Encode the Watching-table rows that are prose expectations, previously
# re-derived by hand each run (two false zeros from hand greps in run 6 alone).


def _spec_with_trigger(expect: str, pattern: str = "in beta"):
    from channel_specs import ChannelSpec, ProseTrigger
    return ChannelSpec(
        key="t", title="t", url="https://x", marker="MARK", surface="both",
        extractors=(),
        prose_triggers=(ProseTrigger("trig", pattern, expect, "why it matters"),),
    )


def test_present_trigger_fires_when_the_sentence_disappears():
    fired = dc.evaluate_triggers("MARK body without the phrase", _spec_with_trigger("present"))
    assert len(fired) == 1 and fired[0]["key"] == "trig"
    assert "gone" in fired[0]["why"]


def test_present_trigger_stays_quiet_while_the_sentence_remains():
    assert dc.evaluate_triggers("MARK still in beta today", _spec_with_trigger("present")) == []


def test_absent_trigger_fires_when_the_token_appears():
    fired = dc.evaluate_triggers("MARK now: /v1/hooks", _spec_with_trigger("absent", "/v1/"))
    assert len(fired) == 1 and "appeared" in fired[0]["why"]


def test_absent_trigger_stays_quiet_while_the_token_is_missing():
    assert dc.evaluate_triggers("MARK console only", _spec_with_trigger("absent", "/v1/")) == []


def test_a_bad_trigger_pattern_fires_rather_than_silently_passing():
    """A broken trigger reading as 'all clear' is the failure this replaces."""
    fired = dc.evaluate_triggers("MARK", _spec_with_trigger("present", "([unclosed"))
    assert len(fired) == 1 and "bad trigger pattern" in fired[0]["why"]


def test_fired_trigger_is_drift_class_for_the_channel(tmp_path):
    spec = _spec_with_trigger("present")
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "t.md").write_text("MARK but the phrase is gone", encoding="utf-8")
    r = dc.process(spec, tmp_path, fx, "2026-08-22", update=False)
    assert r.verdict == dc.TRIGGER_FIRED
    assert r.fired_triggers and r.fired_triggers[0]["key"] == "trig"


def test_extractor_drift_outranks_trigger_as_verdict_but_both_render(tmp_path):
    """Selecting report sections by channel VERDICT would silently drop one of
    the two signals when a channel carries both."""
    from channel_specs import ChannelSpec, Extractor, ProseTrigger
    spec = ChannelSpec(
        key="t", title="t", url="https://x", marker="MARK", surface="both",
        extractors=(Extractor("t-facts", r"`(fact_[a-z]+)`", 1),),
        prose_triggers=(ProseTrigger("trig", "must-stay", "present", "n"),),
    )
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "t.md").write_text("MARK must-stay `fact_one`", encoding="utf-8")
    dc.process(spec, tmp_path, fx, "2026-08-22", update=True)
    (fx / "t.md").write_text("MARK `fact_one` `fact_two`", encoding="utf-8")
    r = dc.process(spec, tmp_path, fx, "2026-08-22", update=False)
    assert r.verdict == dc.DRIFT
    assert r.fired_triggers, "the fired trigger was lost behind the DRIFT verdict"
    report = dc.render([r])
    assert "WATCHING TRIGGERS FIRED" in report
    assert "+ fact_two" in report


# --- report display: docs-baseline vs held-out (run 6) -----------------------


def test_drift_report_separates_docs_baseline_from_held_out(tmp_path):
    """'39 baseline -> 36 live' read as a 3-value REMOVAL when it was +1 with 4
    held out. The report must print the docs-sourced count the diff ran against."""
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-07-27", update=True)

    bp = dc.baseline_path(tmp_path, "otel-events")
    data = json.loads(bp.read_text())
    data["values"] = sorted(data["values"] + ["claude_code.subagent_completed"])
    data["observed_values"] = ["claude_code.subagent_completed"]
    bp.write_text(json.dumps(data, indent=2) + "\n")

    grown = FIXTURE_OTEL + "\n#### S\n**Event Name**: `claude_code.sandbox_denied`\n"
    fx2 = _fixture_dir(tmp_path, grown, key="otel")
    r = dc.process(relaxed, tmp_path, fx2, "2026-07-28", update=False)
    report = dc.render([r])
    n = len(EXPECTED_EVENTS)
    assert f"{n} docs-baseline -> {n + 1} live (+1 held out)" in report
    assert f"{n + 1} baseline ->" not in report, "combined count re-introduces the misread"


# --- fetched-page persistence (run 6) ----------------------------------------


def test_fetched_page_is_persisted_to_pages_dir(tmp_path):
    fx = _fixture_dir(tmp_path, FIXTURE_OTEL)
    pages = tmp_path / "pages"
    relaxed = _otel_events_only(BY_KEY["otel"])
    dc.process(relaxed, tmp_path, fx, "2026-08-22", update=False, pages_dir=pages)
    saved = pages / "otel.md"
    assert saved.exists()
    assert "claude_code.user_prompt" in saved.read_text(encoding="utf-8")


# --- Sources Log auto-bump (run 6) --------------------------------------------


_INTEL_FIXTURE = """# run log
## Sources Log
| Channel | Last OK | Marker asserted | Notes |
|---|---|---|---|
| `otel` | 2026-08-11 | `X` | narrative note that must survive |
| `zdr` | 2026-08-01 | `Y` | another note |
"""


def _intel_kb(tmp_path) -> Path:
    d = tmp_path / "reference" / "claude-data-channels"
    d.mkdir(parents=True)
    (d / "INTELLIGENCE.md").write_text(_INTEL_FIXTURE, encoding="utf-8")
    return tmp_path


def test_sources_log_bumps_only_fetched_ok_channels(tmp_path):
    kb = _intel_kb(tmp_path)
    results = [
        dc.ChannelResult("otel", "t", "u", dc.CLEAN, fetched_ok=True),
        dc.ChannelResult("zdr", "t", "u", dc.FETCH_FAILED, fetched_ok=False),
    ]
    missing = dc.update_sources_log(kb, results, "2026-08-22")
    text = (kb / "reference" / "claude-data-channels" / "INTELLIGENCE.md").read_text()
    assert "| `otel` | 2026-08-22 |" in text
    assert "| `zdr` | 2026-08-01 |" in text, "a FAILED channel's date must NOT advance"
    assert "narrative note that must survive" in text
    assert missing == []


def test_sources_log_reports_channels_with_no_row(tmp_path):
    """Run 5 found 8 registered channels silently absent from the log — an
    incomplete log reads as the coverage list. Missing rows are REPORTED, never
    silently created (the notes column needs a human sentence)."""
    kb = _intel_kb(tmp_path)
    results = [dc.ChannelResult("brand-new", "t", "u", dc.CLEAN, fetched_ok=True)]
    assert dc.update_sources_log(kb, results, "2026-08-22") == ["brand-new"]


# --- code freshness gate (run 6) ----------------------------------------------
# Run 6 initially executed a 143-commit-stale ~/.claude and reproduced the exact
# reconcile-leg budget bug PR #1960 had already fixed. Same fake-git approach as the
# baseline gate's tests.


def test_current_code_reports_fresh(monkeypatch):
    run, _ = _fake_git(None, behind=0)
    monkeypatch.setattr(dc.subprocess, "run", run)
    assert dc.code_freshness()[0] == "FRESH"


def test_stale_code_reports_stale_and_names_the_worktree_fix(monkeypatch):
    run, _ = _fake_git(None, behind=143)
    monkeypatch.setattr(dc.subprocess, "run", run)
    status, detail = dc.code_freshness()
    assert status == "STALE"
    assert "worktree add" in detail, "the fix must be one pasteable command"


def test_code_freshness_unknown_on_failed_fetch_warns_not_fresh(monkeypatch):
    run, _ = _fake_git(None, behind=0, fetch_rc=1)
    monkeypatch.setattr(dc.subprocess, "run", run)
    assert dc.code_freshness()[0] == "UNKNOWN"


def test_non_git_code_copy_is_unknown_not_stale(monkeypatch):
    """The code legitimately runs from non-git copies (marketplace install);
    UNKNOWN warns and proceeds — unlike the baseline gate, which protects
    WRITES and must refuse."""
    run, _ = _fake_git(None, behind=0, is_repo=False)
    monkeypatch.setattr(dc.subprocess, "run", run)
    assert dc.code_freshness()[0] == "UNKNOWN"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
