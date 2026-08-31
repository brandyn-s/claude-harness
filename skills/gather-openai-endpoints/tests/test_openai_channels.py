"""Fixture tests for the OpenAI channel registry driven through the shared engine.

Hermetic: offline fixtures (committed snapshots of the live pages fetched
2026-08-22), a tmp-path KB, no network, no credentials. The engine under test
is the sibling skill's diff_channels.py invoked with --specs pointing at
openai_channel_specs.py — which is exactly how the skill runs it, so these
tests also pin the cross-skill loading contract.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = SKILL_DIR / "tests" / "fixtures"
SPECS = SKILL_DIR / "scripts" / "openai_channel_specs.py"
LAUNCHER = SKILL_DIR / "scripts" / "diff_openai_channels.py"
ENGINE = SKILL_DIR.parents[0] / "_shared" / "endpoint-drift" / "diff_engine.py"

sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR.parents[0] / "_shared" / "endpoint-drift"))
import openai_channel_specs as specs  # noqa: E402


def run_engine(kb: Path, fixtures: Path, *extra: str) -> subprocess.CompletedProcess:
    # Through the launcher, WITHOUT --specs: every engine run in this suite also
    # proves the launcher's default-registry injection.
    return subprocess.run(
        [sys.executable, str(LAUNCHER),
         "--kb", str(kb),
         "--offline", str(fixtures),
         "--run-date", "2026-08-22",
         *extra],
        capture_output=True, text=True, timeout=120,
    )


def baselines_dir(kb: Path) -> Path:
    return kb / "reference" / "openai-data-channels" / "baselines"


def establish(kb: Path, fixtures: Path) -> None:
    p = run_engine(kb, fixtures, "--update-baseline")
    assert p.returncode == 0, p.stdout + p.stderr


# ---------------------------------------------------------------- registry --

def test_registry_shape():
    assert len(specs.ALL_CHANNELS) == 4
    assert set(specs.BY_KEY) == {
        "platform-admin-reference", "compliance-logs-cookbook", "chatgpt-docs-index",
        "compliance-admin-reference-export",
    }
    assert specs.KB_SUBDIR == "openai-data-channels"
    assert "reconcile_openai_observed" in specs.OBSERVED_HINT


def test_every_channel_has_a_fixture():
    for c in specs.ALL_CHANNELS:
        assert (FIXTURES / f"{c.key}.md").exists(), c.key


# ------------------------------------------------------- extractor values --

def test_admin_reference_extracts_known_slugs():
    import re
    body = (FIXTURES / "platform-admin-reference.md").read_text(encoding="utf-8")
    ex = {e.key: e for e in specs.PLATFORM_ADMIN_REFERENCE.extractors}
    pages = set(re.findall(ex["openai-admin-reference-pages"].pattern, body, re.MULTILINE))
    # Reachability (tdd-mutation item 18): assert known members, not just count.
    assert "resources/organization/subresources/audit_logs" in pages
    assert "resources/organization/subresources/audit_logs/methods/list" in pages
    assert len(pages) >= ex["openai-admin-reference-pages"].min_expected
    groups = set(re.findall(ex["openai-api-resource-groups"].pattern, body, re.MULTILINE))
    assert "organization" in groups
    assert len(groups) >= ex["openai-api-resource-groups"].min_expected


def test_cookbook_extracts_event_type_and_both_scope_segments():
    import re
    body = (FIXTURES / "compliance-logs-cookbook.md").read_text(encoding="utf-8")
    ex = {e.key: e for e in specs.COMPLIANCE_LOGS_COOKBOOK.extractors}
    events = set(re.findall(ex["compliance-event-types"].pattern, body, re.MULTILINE))
    assert "AUTH_LOG" in events
    segs = set(re.findall(ex["compliance-scope-segments"].pattern, body, re.MULTILINE))
    # The cookbook documents BOTH; a probe memory once said "workspaces only"
    # and was refuted by this fixture (flaw log 2026-08-22).
    assert segs == {"workspaces", "organizations"}


# ------------------------------------------------------- engine round-trip --

def test_first_run_establishes_then_second_run_is_clean(tmp_path):
    p = run_engine(tmp_path, FIXTURES, "--update-baseline")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OPENAI DATA-CHANNEL DRIFT REPORT" in p.stdout
    assert "NO BASELINE" in p.stdout
    files = sorted(f.name for f in baselines_dir(tmp_path).glob("*.json"))
    assert files == [
        "admin-reference-event-types.json",
        "admin-reference-routes.json",
        "chatgpt-doc-pages.json",
        "compliance-event-types.json",
        "compliance-scope-segments.json",
        "openai-admin-reference-pages.json",
        "openai-api-resource-groups.json",
    ]
    # Baselines land under the OpenAI subdir, not the Anthropic one.
    assert not (tmp_path / "reference" / "claude-data-channels").exists()

    p2 = run_engine(tmp_path, FIXTURES)
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert "DRIFT" not in [ln.strip("- ") for ln in p2.stdout.splitlines()
                           if ln.strip().startswith("-- DRIFT")]


def test_removed_admin_page_reports_drift_exit_1(tmp_path):
    establish(tmp_path, FIXTURES)
    mutated = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, mutated)
    fx = mutated / "platform-admin-reference.md"
    body = fx.read_text(encoding="utf-8")
    needle = ("https://developers.openai.com/api/reference/resources/organization/"
              "subresources/invites/methods/create.md")
    assert needle in body  # reachability: the mutation must actually remove a fact
    fx.write_text(body.replace(needle, ""), encoding="utf-8")

    p = run_engine(tmp_path, mutated)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "resources/organization/subresources/invites/methods/create" in p.stdout
    assert "[REMOVED]" in p.stdout


def test_missing_compliance_guide_fires_trigger_exit_1(tmp_path):
    establish(tmp_path, FIXTURES)
    mutated = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, mutated)
    fx = mutated / "chatgpt-docs-index.md"
    body = fx.read_text(encoding="utf-8")
    assert "docs/enterprise/compliance-api.md" in body
    # Drop only the trigger's line; the marker ("Compliance API") survives in
    # the section header so this exercises the TRIGGER, not CHANNEL_DEAD.
    kept = [ln for ln in body.splitlines() if "docs/enterprise/compliance-api.md" not in ln]
    fx.write_text("\n".join(kept), encoding="utf-8")

    p = run_engine(tmp_path, mutated)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "compliance-api-guide-listed" in p.stdout


def test_gutted_page_reports_instrument_blind_not_removal(tmp_path):
    establish(tmp_path, FIXTURES)
    mutated = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, mutated)
    # Keep the liveness marker but destroy the fact declarations: the verdict
    # must be INSTRUMENT_BLIND (detector bug), never a mass REMOVED.
    (mutated / "platform-admin-reference.md").write_text(
        "# OpenAI API\n\n## Administration\n\n(page restructured)\n",
        encoding="utf-8",
    )
    p = run_engine(tmp_path, mutated)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "INSTRUMENT_BLIND" in p.stdout
    assert "[REMOVED]" not in p.stdout


def test_observed_values_are_held_out_of_the_docs_diff(tmp_path):
    """The probe-discovered event types (AUDIT_LOG etc.) must never report as
    REMOVED merely because the cookbook does not list them."""
    establish(tmp_path, FIXTURES)
    b = baselines_dir(tmp_path) / "compliance-event-types.json"
    data = json.loads(b.read_text(encoding="utf-8"))
    probe_only = ["APP_AUTH_LOG", "APP_LOG", "AUDIT_LOG", "CODEX_LOG",
                  "CODEX_SECURITY_LOG", "CUSTOM_AGENTS_LOG"]
    data["values"] = sorted(set(data["values"]) | set(probe_only))
    data["observed_values"] = probe_only
    data["observed_source"] = "live probe 2026-08-04 (memory: openai-compliance-logs-platform)"
    b.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    p = run_engine(tmp_path, FIXTURES)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "[REMOVED]" not in p.stdout
    assert "OBSERVED_ONLY" in p.stdout


def test_specs_flag_rejects_missing_file(tmp_path):
    p = subprocess.run(
        [sys.executable, str(ENGINE), "--specs", str(tmp_path / "nope.py"),
         "--kb", str(tmp_path), "--offline", str(FIXTURES), "--run-date", "2026-08-22"],
        capture_output=True, text=True, timeout=60,
    )
    assert p.returncode == 2
    assert "not found" in p.stderr


# ------------------------------------------------- manual-export channel --

def test_local_source_missing_is_reported_not_failed(tmp_path):
    """An absent manual export is a standing gap: loud in the report, exit 0."""
    import diff_engine
    from spec_types import ChannelSpec, Extractor

    spec = ChannelSpec(
        key="x-export", title="t", url="https://example.invalid/login-gated",
        marker="anything", surface="test",
        local_path=str(tmp_path / "does-not-exist.md"),
        extractors=(Extractor(key="x-vals", pattern=r"(FOO_\w+)", min_expected=1),),
    )
    r = diff_engine.process(spec, tmp_path, offline=None, run_date="2026-08-22",
                            update=False)
    assert r.verdict == diff_engine.LOCAL_SOURCE_MISSING
    assert "refresh it from" in r.detail
    rendered = diff_engine.render([r])
    assert "LOCAL SOURCE MISSING" in rendered
    assert "run NOT failed" in rendered


def test_local_source_present_extracts_like_a_fetched_page(tmp_path):
    import diff_engine
    from spec_types import ChannelSpec, Extractor

    src = tmp_path / "export.md"
    src.write_text("marker FOO_A and FOO_B\n", encoding="utf-8")
    spec = ChannelSpec(
        key="x-export", title="t", url="https://example.invalid", marker="marker",
        surface="test", local_path=str(src),
        extractors=(Extractor(key="x-vals", pattern=r"(FOO_\w+)", min_expected=1),),
    )
    r = diff_engine.process(spec, tmp_path, offline=None, run_date="2026-08-22",
                            update=True)
    assert r.verdict == diff_engine.NO_BASELINE
    # Direct-import runs keep the engine's default (Anthropic) KB subdir; read
    # through the engine's own resolver rather than assuming a vendor path.
    got = json.loads(diff_engine.baseline_path(tmp_path, "x-vals")
                     .read_text(encoding="utf-8"))
    assert got["values"] == ["FOO_A", "FOO_B"]


def test_export_fixture_pins_the_extractors():
    import re
    body = (FIXTURES / "compliance-admin-reference-export.md").read_text(encoding="utf-8")
    ex = {e.key: e for e in specs.COMPLIANCE_ADMIN_REFERENCE_EXPORT.extractors}
    tokens = set(re.findall(ex["admin-reference-event-types"].pattern, body, re.MULTILINE))
    # Suffix-less names are the regression this extractor exists for: a *_LOG
    # pattern silently missed both (caught on the first real capture).
    assert {"CONVERSATION_MESSAGE", "COSTS", "AUDIT_LOG", "APP_LOG"} <= tokens
    assert len(tokens) >= ex["admin-reference-event-types"].min_expected
    routes = set(re.findall(ex["admin-reference-routes"].pattern, body, re.MULTILINE))
    assert "/compliance/workspaces/{workspace_id}/logs" in routes
    assert "/compliance/organizations/{organization_id}/max_event_time" in routes
    assert len(routes) >= ex["admin-reference-routes"].min_expected
    # The vendor spec's enums are deliberately non-exhaustive; if the literal
    # placeholder ever disappears, the enum may have become complete — re-grade.
    assert "etc..." in body


# ------------------------------------------------------ reconcile script --

def test_reconcile_classify_probe_semantics():
    import reconcile_openai_observed as ro
    assert ro.classify_probe(200, "")[0] == "REACHABLE"
    assert ro.classify_probe(400, '{"error": "after is required"}')[0] == "REACHABLE"
    assert ro.classify_probe(400, '{"error": "Invalid event_type FOO"}')[0] == "INVALID_VALUE"
    assert ro.classify_probe(401, "")[0] == "WRONG_KEY_CLASS"
    assert ro.classify_probe(403, "")[0] == "WRONG_SCOPE"
    assert ro.classify_probe(404, "")[0] == "ABSENT"
    assert ro.classify_probe(None, "timeout")[0] == "PROBE_FAILED"


def test_reconcile_refuses_non_get_probe():
    import reconcile_openai_observed as ro
    with pytest.raises(ro.UnsafeProbe):
        ro.probe_endpoint("https://example.invalid/x", "k", method="DELETE")


def test_reconcile_observed_merges_with_provenance(tmp_path):
    import reconcile_openai_observed as ro
    b = tmp_path / "reference" / "openai-data-channels" / "baselines"
    b.mkdir(parents=True)
    (b / "compliance-event-types.json").write_text(json.dumps(
        {"extractor": "compliance-event-types", "values": ["AUTH_LOG"], "count": 1}),
        encoding="utf-8")
    rep = ro.reconcile_observed(tmp_path, {"compliance-event-types": ["AUTH_LOG", "NEW_LOG"]},
                                update=True)
    assert rep["compliance-event-types"]["status"] == "UNDOCUMENTED"
    assert rep["compliance-event-types"]["undocumented"] == ["NEW_LOG"]
    data = json.loads((b / "compliance-event-types.json").read_text(encoding="utf-8"))
    assert "NEW_LOG" in data["values"] and data["observed_values"] == ["NEW_LOG"]
    # Second pass reconciles cleanly — merge is idempotent.
    rep2 = ro.reconcile_observed(tmp_path, {"compliance-event-types": ["AUTH_LOG", "NEW_LOG"]},
                                 update=True)
    assert rep2["compliance-event-types"]["status"] == "RECONCILED"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
