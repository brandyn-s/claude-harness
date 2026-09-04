"""Oracle calibration test (SPEC.md §"Calibration").

Loads the labeled findings in `tests/golden-findings/calibration/
findings.yaml` and measures Layer A's TPR / TNR / refusal-rate.
Fails the build if TPR < 0.95 or TNR < 0.80 — the documented floor
for autonomous use (SPEC.md §"Out of scope").

Also exercises the trace infrastructure: every reverify invocation
must write a TraceRecord with the schema in SPEC.md §"Trace contract".
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CALIBRATION_DIR = Path(__file__).resolve().parent / "golden-findings" / "calibration"


def _load_oracle():
    """Import the oracle module from skills/_shared/oracle/."""
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    if "oracle" in sys.modules:
        del sys.modules["oracle"]
    if "oracle.finding" in sys.modules:
        del sys.modules["oracle.finding"]
    if "oracle.reverify" in sys.modules:
        del sys.modules["oracle.reverify"]
    if "oracle.trace" in sys.modules:
        del sys.modules["oracle.trace"]
    from oracle import finding as f_mod  # noqa: E402
    from oracle import reverify as r_mod  # noqa: E402
    from oracle import trace as t_mod  # noqa: E402
    return f_mod, r_mod, t_mod


# Documented floors (SPEC.md §"Calibration results").
MIN_TPR = 0.95
MIN_TNR = 0.80
# ERROR-pathway calibration (added 2026-05-26 alongside the rc>=2 and
# python instrument-failure contracts). TPR floor is 1.0 because every
# known-ERROR entry is deterministic — a regression that re-introduces
# the conflation will drop a contract case to STALE / STILL-FIRES and
# fail loud. FPR ceiling is small but non-zero to allow the instrument-
# failure pattern list to be slightly conservative without false-alarming
# every well-formed predicate.
MIN_ERR_TPR = 1.0
MAX_ERR_FPR = 0.05

# Specificity / gamed-stratum floors (Phase 1 anti-gaming spine). The
# guard must catch every curated gamed (vacuous) reproducer and flag
# none of the specific controls. See findings-gamed.yaml.
MIN_GAMED_TPR = 0.95   # fraction of gamed reproducers caught as non-specific
MAX_GAMED_FPR = 0.0    # fraction of specific controls wrongly flagged


def test_calibration_tpr_tnr_above_floor(tmp_path, monkeypatch):
    """Run reverify against the labeled calibration set and verify
    TPR and TNR exceed the SPEC-documented floors.

    A regression here means the oracle has started producing too many
    false positives (low TNR) or missing real bugs (low TPR). Either
    is a release-blocking signal — do not silence the test; fix the
    reproducer or the layer."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()
    fs = f_mod.load_findings(CALIBRATION_DIR / "findings.yaml")
    assert fs, "calibration set is empty"

    # Partition by ground-truth label. `expected_status` (added 2026-05-26)
    # takes precedence — currently only used for ERROR-pathway entries.
    # `expected_fires` (true/false) is the v3 schema for STILL-FIRES /
    # STALE predicate results.
    def _expected_status(f) -> str:
        es = str(f.extra.get("expected_status", "")).upper()
        if es:
            return es
        ef = str(f.extra.get("expected_fires", "")).lower()
        if ef == "true":
            return "STILL-FIRES"
        if ef == "false":
            return "STALE"
        return ""

    expected_true = [f for f in fs if _expected_status(f) == "STILL-FIRES"]
    expected_false = [f for f in fs if _expected_status(f) == "STALE"]
    expected_error = [f for f in fs if _expected_status(f) == "ERROR"]
    assert len(expected_true) >= 10, "need at least 10 known-true findings"
    assert len(expected_false) >= 10, "need at least 10 known-false findings"
    # ERROR pathway calibration added 2026-05-26 to pin the contracts
    # established by PR #979 (grep rc>=2 -> ERROR) and PR #981 (python
    # instrument failure -> ERROR). Without these the calibration set
    # could pass at TPR=TNR=1.0 while the conflation regressed silently.
    assert len(expected_error) >= 4, "need at least 4 known-ERROR findings"

    results = r_mod.reverify(fs, REPO)
    by_id = {(r.finding.skill, r.finding.code, r.finding.description): r for r in results}

    tp = fp = tn = fn = 0
    # ERROR pathway: tp_err = correctly classified ERROR;
    #                fn_err = expected ERROR but observed something else;
    #                fp_err = unexpected ERROR on a known-fires/known-stale finding.
    tp_err = fn_err = fp_err = 0
    refusals = 0  # MANUAL only — ERROR is now a measured outcome, not a refusal.
    misclassified: list[str] = []
    for f in fs:
        r = by_id[(f.skill, f.code, f.description)]
        expected = _expected_status(f)
        if r.status == "MANUAL":
            refusals += 1
            continue
        if expected == "ERROR":
            if r.status == "ERROR":
                tp_err += 1
            else:
                fn_err += 1
                misclassified.append(
                    f"FN(err): {f.skill}/{f.code} expected ERROR, observed "
                    f"{r.status} ({f.description[:50]!r})"
                )
            continue
        # Predicate-pathway (STILL-FIRES / STALE) accounting.
        if r.status == "ERROR":
            # Known-fires or known-stale entry that surprised the oracle.
            fp_err += 1
            misclassified.append(
                f"FP(err): {f.skill}/{f.code} expected {expected}, "
                f"observed ERROR — {r.evidence[:80]!r}"
            )
            continue
        fired = (r.status == "STILL-FIRES")
        expected_true_b = (expected == "STILL-FIRES")
        if expected_true_b and fired:
            tp += 1
        elif expected_true_b and not fired:
            fn += 1
            misclassified.append(f"FN: {f.skill}/{f.code} ({f.description[:60]!r}) — {r.evidence}")
        elif not expected_true_b and not fired:
            tn += 1
        else:
            fp += 1
            misclassified.append(f"FP: {f.skill}/{f.code} ({f.description[:60]!r}) — {r.evidence}")

    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    err_tpr = tp_err / (tp_err + fn_err) if (tp_err + fn_err) else 0.0
    # FPR for the ERROR pathway: ERROR observed when not expected,
    # over the predicate-pathway population.
    err_fpr = fp_err / (tp + fn + tn + fp + fp_err) if (tp + fn + tn + fp + fp_err) else 0.0
    refusal_rate = refusals / len(fs)

    # Report the numbers regardless; assert at the end.
    print("\n=== Layer A calibration ===")
    print(f"predicate TPR={tpr:.3f} (need >= {MIN_TPR})")
    print(f"predicate TNR={tnr:.3f} (need >= {MIN_TNR})")
    print(f"ERROR-pathway TPR={err_tpr:.3f} (need >= {MIN_ERR_TPR})")
    print(f"ERROR-pathway FPR={err_fpr:.3f} (need <= {MAX_ERR_FPR})")
    print(f"refusal_rate={refusal_rate:.3f}")
    print(f"TP={tp} TN={tn} FP={fp} FN={fn} "
          f"TP_err={tp_err} FN_err={fn_err} FP_err={fp_err} refusals={refusals}")
    if misclassified:
        print("Misclassified:")
        for m in misclassified:
            print(f"  {m}")

    assert tpr >= MIN_TPR, f"predicate TPR={tpr:.3f} below floor {MIN_TPR}"
    assert tnr >= MIN_TNR, f"predicate TNR={tnr:.3f} below floor {MIN_TNR}"
    assert err_tpr >= MIN_ERR_TPR, (
        f"ERROR-pathway TPR={err_tpr:.3f} below floor {MIN_ERR_TPR} — "
        f"the rc>=2 / instrument-failure conflation has regressed; "
        f"see oracle/SPEC.md 'Exit-code contract' sections"
    )
    assert err_fpr <= MAX_ERR_FPR, (
        f"ERROR-pathway FPR={err_fpr:.3f} above ceiling {MAX_ERR_FPR} — "
        f"the oracle is raising ERROR on well-formed predicates "
        f"(the instrument-failure pattern list is too aggressive)"
    )


def test_oracle_vs_truth_kappa_above_floor(tmp_path, monkeypatch):
    """Cohen's κ between Layer A's verdict and the adjudicated ground-truth
    label over the predicate-pathway calibration entries — a chance-
    corrected companion to the TPR/TNR floors (raw accuracy overstates
    agreement when one class dominates). κ >= 0.7 (substantial). Uses
    existing data; the inter-rater κ over label_a/label_b is a separate,
    human-populated gate documented in SPEC §'Layer profiles'."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    sys.modules.pop("oracle.kappa", None)
    from oracle import kappa as k_mod  # noqa: E402

    fs = f_mod.load_findings(CALIBRATION_DIR / "findings.yaml")
    results = {(r.finding.skill, r.finding.code, r.finding.description): r
               for r in r_mod.reverify(fs, REPO)}
    truth, observed = [], []
    for f in fs:
        ef = str(f.extra.get("expected_fires", "")).lower()
        if ef not in ("true", "false"):
            continue  # ERROR-pathway / unlabeled entries aren't fires/not-fires
        r = results[(f.skill, f.code, f.description)]
        if r.status not in ("STILL-FIRES", "STALE"):
            continue
        truth.append(ef)
        observed.append("true" if r.status == "STILL-FIRES" else "false")

    assert len(truth) >= 20, f"need >= 20 predicate-pathway entries, got {len(truth)}"
    kappa = k_mod.cohens_kappa(truth, observed)
    print(f"\noracle-vs-truth kappa={kappa:.3f} ({k_mod.interpret(kappa)})")
    assert kappa >= 0.7, (
        f"oracle-vs-truth kappa={kappa:.3f} below 0.7 floor "
        f"({k_mod.interpret(kappa)}) — Layer A agreement with ground truth "
        f"has degraded beyond what raw TPR/TNR reveals"
    )


def test_every_reverify_writes_a_trace_record(tmp_path, monkeypatch):
    """Trace contract per SPEC §"Trace contract": every layer-A
    invocation produces one TraceRecord with all required fields."""
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace_file))
    f_mod, r_mod, t_mod = _load_oracle()
    fs = f_mod.load_findings(CALIBRATION_DIR / "findings.yaml")
    r_mod.reverify(fs, REPO)
    records = t_mod.read_records(trace_file)
    assert len(records) == len(fs), (
        f"expected {len(fs)} trace records, got {len(records)}"
    )
    for rec in records:
        # Required fields per SPEC.md §"Trace contract"
        assert rec.layer == "A"
        assert rec.finding_id, "finding_id required"
        assert rec.skill, "skill required"
        assert rec.verdict in (
            "STILL-FIRES", "STALE", "MANUAL", "ERROR",
        ), f"unexpected verdict: {rec.verdict!r}"
        assert rec.ts, "timestamp required"
        assert rec.procedure_version, "procedure_version required"
        assert rec.latency_ms >= 0
        assert "reproducer_type" in rec.input
        assert "reproducer_command_sha" in rec.input
        assert rec.schema_version == t_mod.TRACE_SCHEMA_VERSION


def test_grep_error_exit_routes_to_ERROR_not_STALE(tmp_path, monkeypatch):
    """Contract gap fix: grep exits 0=match, 1=no-match, >=2=error.
    The original implementation mapped any non-zero rc to fires=False
    (or fires=True for grep_absent), so a typo'd path, bad regex, or
    permission failure looked identical to "bug fixed." That's a
    silent misclassification — STALE when the right answer is ERROR.

    This test pins the corrected contract for both grep types so a
    future refactor can't silently regress it.
    """
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()

    # Real file with known content — used to anchor the "no match"
    # (STALE) case so it stays distinct from the error case.
    target = tmp_path / "real.txt"
    target.write_text("the quick brown fox\n", encoding="utf-8")
    # bash on Windows treats \U \B \T as escape sequences in argv
    # strings; use forward slashes so the path survives intact.
    target_posix = target.as_posix()
    tmp_posix = tmp_path.as_posix()

    cases = [
        # (label, reproducer, expected_status)
        # grep over a file that doesn't exist → grep exits 2 → ERROR.
        ("grep_file_not_found",
         f_mod.Reproducer(type="grep", command=f"grep -q foo {tmp_posix}/does-not-exist.txt"),
         "ERROR"),
        # grep_absent over a file that doesn't exist → ERROR, not
        # STILL-FIRES. (Pre-fix: rc=2 → fires=True → STILL-FIRES.)
        ("grep_absent_file_not_found",
         f_mod.Reproducer(type="grep_absent", command=f"grep -q foo {tmp_posix}/does-not-exist.txt"),
         "ERROR"),
        # Real "no match" case still maps to STALE.
        ("grep_no_match_is_STALE",
         f_mod.Reproducer(type="grep", command=f"grep -q nothing-matches {target_posix}"),
         "STALE"),
        # Real "match" case still maps to STILL-FIRES.
        ("grep_match_is_STILL_FIRES",
         f_mod.Reproducer(type="grep", command=f"grep -q fox {target_posix}"),
         "STILL-FIRES"),
        # grep_absent: real file lacking the pattern → fires=True
        # (STILL-FIRES). Confirms the inverted contract still works.
        ("grep_absent_no_match_is_STILL_FIRES",
         f_mod.Reproducer(type="grep_absent", command=f"grep -q nothing-matches {target_posix}"),
         "STILL-FIRES"),
    ]
    for label, repro, expected in cases:
        finding = f_mod.Finding(
            skill="contract-test", code="X", severity="info",
            label="doc-fix", description=label, reproducer=repro,
        )
        [res] = r_mod.reverify([finding], tmp_path)
        assert res.status == expected, (
            f"case {label}: expected {expected}, got {res.status} "
            f"(evidence={res.evidence!r})"
        )


def test_python_instrument_failure_routes_to_ERROR(tmp_path, monkeypatch):
    """Python reproducer contract: rc!=0 from a true predicate raise
    is STILL-FIRES, but rc!=0 from a reproducer-instrument failure
    (SyntaxError, NameError, ImportError, etc.) is ERROR — not STALE
    nor STILL-FIRES. Without this routing a typo'd snippet produces
    the same verdict as a real bug, and Layer D fix-loop misreports
    fix outcomes. Same conflation class as the pre-2026-05-25 grep
    rc>=2 bug.
    """
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()

    cases = [
        # (label, snippet, expected_status)
        ("syntax_error_is_ERROR",
         "this is not valid python ::", "ERROR"),
        ("module_not_found_is_ERROR",
         "import this_module_definitely_does_not_exist_xyzzy", "ERROR"),
        ("name_error_is_ERROR",
         "some_undefined_variable", "ERROR"),
        ("attribute_error_is_ERROR",
         "import sys; sys.this_attribute_does_not_exist", "ERROR"),
        # Intentional raise — author's predicate fired.
        ("intentional_raise_is_STILL_FIRES",
         "raise RuntimeError('bug present')", "STILL-FIRES"),
        ("intentional_assert_is_STILL_FIRES",
         "assert False, 'bug present'", "STILL-FIRES"),
        # Clean exit means snippet evaluated and found no bug.
        ("clean_exit_is_STALE",
         "pass", "STALE"),
        ("sys_exit_zero_is_STALE",
         "import sys; sys.exit(0)", "STALE"),
        # sys.exit(1) without exception is still STILL-FIRES (author
        # signalling "bug present" without raising).
        ("sys_exit_one_is_STILL_FIRES",
         "import sys; sys.exit(1)", "STILL-FIRES"),
    ]
    for label, snippet, expected in cases:
        finding = f_mod.Finding(
            skill="contract-py", code="X", severity="info",
            label="doc-fix", description=label,
            reproducer=f_mod.Reproducer(type="python", command=snippet),
        )
        [res] = r_mod.reverify([finding], tmp_path)
        assert res.status == expected, (
            f"case {label}: expected {expected}, got {res.status} "
            f"(evidence={res.evidence!r})"
        )


def test_bash_instrument_failure_routes_to_ERROR(tmp_path, monkeypatch):
    """Bash reproducer contract (closes the third conflation surface
    after grep and python): rc in {126, 127} OR rc >= 128 when
    rc != expected_exit means instrument failure (command-not-found,
    not-executable, signal-killed) — not a predicate result. Routes
    to ERROR, not STALE.

    If the author explicitly sets expected_exit to one of those rc
    values (e.g. testing whether a command IS missing,
    expected_exit=127), the equality branch wins first and STILL-FIRES
    is returned. The control cases guard against over-correction.
    """
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()

    cases = [
        # (label, command, expected_exit, expected_status)
        ("command_not_found_is_ERROR",
         "this-command-does-not-exist-xyzzy", 0, "ERROR"),
        ("signal_kill_is_ERROR",
         "bash -c 'kill -KILL $$'", 0, "ERROR"),
        # Equality-wins control: explicit expected_exit=127 testing
        # command-absence is a legitimate predicate. STILL-FIRES.
        ("expected_127_is_STILL_FIRES",
         "this-command-does-not-exist-xyzzy", 127, "STILL-FIRES"),
        # Legitimate predicate-result controls:
        ("rc0_matches_expected_is_STILL_FIRES",
         "true", 0, "STILL-FIRES"),
        ("rc1_non_matching_is_STALE",
         "false", 0, "STALE"),
    ]
    for label, command, expected_exit, expected in cases:
        finding = f_mod.Finding(
            skill="contract-bash", code="X", severity="info",
            label="doc-fix", description=label,
            reproducer=f_mod.Reproducer(
                type="bash", command=command, expected_exit=expected_exit,
            ),
        )
        [res] = r_mod.reverify([finding], tmp_path)
        assert res.status == expected, (
            f"case {label}: expected {expected}, got {res.status} "
            f"(evidence={res.evidence!r})"
        )


def test_gamed_stratum_classified_nonspecific():
    """Specificity guard (Phase 1 anti-gaming spine): every curated gamed
    (vacuous) reproducer must be classified non-specific, and no specific
    control may be flagged. Closes the proposer-grades-its-own-homework
    hole — a vacuous predicate (`grep -q .`) fires regardless of content,
    so its STILL-FIRES verdict certifies nothing."""
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for m in ("oracle", "oracle.finding", "oracle.specificity"):
        sys.modules.pop(m, None)
    from oracle import finding as f_mod  # noqa: E402
    from oracle import specificity as sp_mod  # noqa: E402

    gamed_path = CALIBRATION_DIR / "findings-gamed.yaml"
    assert gamed_path.exists(), "gamed stratum fixture missing"
    fs = f_mod.load_findings(gamed_path)

    def _expected(f) -> str:
        return str(f.extra.get("expected_specificity", "")).upper()

    gamed = [f for f in fs if _expected(f) == "NONSPECIFIC"]
    specific = [f for f in fs if _expected(f) == "SPECIFIC"]
    assert len(gamed) >= 4, "need >= 4 gamed reproducers"
    assert len(specific) >= 2, "need >= 2 specific controls"

    def _nonspecific(f) -> bool:
        verdict, _ev = sp_mod.specificity_verdict(f.reproducer, REPO)
        return sp_mod.is_nonspecific(verdict)

    caught = sum(1 for f in gamed if _nonspecific(f))
    false_flagged = sum(1 for f in specific if _nonspecific(f))
    detection = caught / len(gamed)
    false_flag_rate = false_flagged / len(specific)

    print("\n=== specificity guard (gamed stratum) ===")
    print(f"gamed detection={detection:.3f} (need >= {MIN_GAMED_TPR})")
    print(f"specific false-flag={false_flag_rate:.3f} (need <= {MAX_GAMED_FPR})")

    assert detection >= MIN_GAMED_TPR, (
        f"specificity guard caught {caught}/{len(gamed)} gamed reproducers "
        f"(detection {detection:.3f} < floor {MIN_GAMED_TPR}) — vacuous "
        f"predicates would slip through validate_for_dispatch"
    )
    assert false_flag_rate <= MAX_GAMED_FPR, (
        f"specificity guard wrongly flagged {false_flagged}/{len(specific)} "
        f"specific controls (false-flag {false_flag_rate:.3f} > ceiling "
        f"{MAX_GAMED_FPR}) — the guard is over-rejecting legitimate reproducers"
    )


def test_layer_profiles_consistent_with_spec():
    """Phase 2: the profile vector replaces the Tier ladder. Pin the
    PROFILES↔SPEC consistency — keys A-D, the derived-tier alias mapping,
    JSON renderability, honest unmeasured cells, and that SPEC.md
    documents the section and the (deprecated) tier labels."""
    import json as _json
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for m in ("oracle", "oracle.profile"):
        sys.modules.pop(m, None)
    from oracle import profile as p_mod  # noqa: E402

    assert set(p_mod.PROFILES) == {"A", "B", "C", "D"}
    # Derived-tier alias (the deprecated ladder, computed from groundedness).
    expected_tier = {"A": "Tier 2", "B": "Tier 3", "C": "Tier 4", "D": "Tier 2"}
    for layer, prof in p_mod.PROFILES.items():
        assert p_mod.derived_tier(prof) == expected_tier[layer], layer
    # JSON render: 4 entries, each carrying derived_tier.
    rows = _json.loads(p_mod.render_profiles("json"))
    assert len(rows) == 4 and all("derived_tier" in r for r in rows)
    # Markdown render includes the ladder aliases.
    md = p_mod.render_profiles("markdown")
    assert "Tier 2" in md and "Tier 3" in md and "Tier 4" in md
    # Layer B's unmeasured cells must stay honest (None), not fabricated.
    assert p_mod.PROFILES["B"].soundness is None
    # SPEC mirror exists and documents the section + the derived tiers.
    spec = (REPO / "skills" / "_shared" / "oracle" / "SPEC.md").read_text(encoding="utf-8")
    assert "## Layer profiles" in spec
    for t in ("Tier 2", "Tier 3", "Tier 4"):
        assert t in spec


def test_spec_md_has_required_sections():
    """SPEC.md must document the verdict semantics for each layer
    (Principle 1) and the trace contract (Principle 5). This test
    pins the structure so a careless edit doesn't drop a section."""
    spec = (REPO / "skills" / "_shared" / "oracle" / "SPEC.md").read_text(encoding="utf-8")
    required = [
        "## Layer A — `reverify`",
        "## Layer B — `ensemble`",
        "## Layer C — `corpus`",
        "## Layer D — `fix_loop`",
        "Positive verdict semantics",
        "Negative verdict semantics",
        "Tier.",
        "Decorrelation analysis",
        "Cost asymmetry",
        "Calibration",
        "Recalibration schedule",
        "## Trace contract",
        "## Cascade composition",
        "## Out of scope",
    ]
    missing = [s for s in required if s not in spec]
    assert not missing, f"SPEC.md missing required sections: {missing}"


def test_layer_b_does_not_claim_decorrelation():
    """Layer B's docstring must explicitly acknowledge it is NOT a
    decorrelated oracle. The Kim et al. result + the renaming to
    "ensemble" matters precisely because the previous "consensus"
    framing implied a guarantee the mechanism does not provide."""
    ensemble_src = (REPO / "skills" / "_shared" / "oracle" / "ensemble.py").read_text(encoding="utf-8")
    # Must contain honest framing markers
    for marker in ("NOT a decorrelated oracle", "Kim et al", "same mechanism"):
        assert marker.lower() in ensemble_src.lower(), (
            f"ensemble.py missing honest-framing marker: {marker!r}"
        )


# ──────────────────────────────────────────────────────────────────
# QoL bundle (added 2026-05-26): configurable timeout, expect_type,
# verified_at freshness, Layer D regression check.
# ──────────────────────────────────────────────────────────────────


def test_reproducer_timeout_env_var_overrides_default(monkeypatch):
    """AUDIT_SKILL_ORACLE_TIMEOUT env var configures the per-reproducer
    subprocess timeout. Default 30s; the override lets a reproducer
    that legitimately needs more (e.g. wc on a large file) survive."""
    f_mod, _, _ = _load_oracle()
    monkeypatch.delenv("AUDIT_SKILL_ORACLE_TIMEOUT", raising=False)
    assert f_mod._reproducer_timeout() == 30.0
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TIMEOUT", "120")
    assert f_mod._reproducer_timeout() == 120.0
    # Malformed override falls back to default.
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TIMEOUT", "not-a-number")
    assert f_mod._reproducer_timeout() == 30.0


def test_reproducer_expect_type_dir_vs_file(tmp_path, monkeypatch):
    """file_exists / file_missing with expect_type=dir asserts the
    path is a directory; expect_type=file asserts a file. Default
    `either` matches both (back-compat)."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()
    real_file = tmp_path / "a.txt"
    real_file.write_text("x", encoding="utf-8")
    real_dir = tmp_path / "sub"
    real_dir.mkdir()

    cases = [
        ("either_matches_file",
         "file_exists", "a.txt", "either", "STILL-FIRES"),
        ("either_matches_dir",
         "file_exists", "sub", "either", "STILL-FIRES"),
        ("file_exists_dir_with_expect_file_misses",
         "file_exists", "sub", "file", "STALE"),
        ("file_exists_file_with_expect_dir_misses",
         "file_exists", "a.txt", "dir", "STALE"),
        ("file_exists_dir_with_expect_dir_matches",
         "file_exists", "sub", "dir", "STILL-FIRES"),
        ("file_exists_file_with_expect_file_matches",
         "file_exists", "a.txt", "file", "STILL-FIRES"),
        ("file_missing_present_file_with_expect_dir_fires",
         "file_missing", "a.txt", "dir", "STILL-FIRES"),
        ("file_missing_truly_absent",
         "file_missing", "nope.txt", "either", "STILL-FIRES"),
    ]
    for label, type_, path, expect_type, expected in cases:
        finding = f_mod.Finding(
            skill="path-type", code="X", severity="info",
            label="doc-fix", description=label,
            reproducer=f_mod.Reproducer(type=type_, path=path, expect_type=expect_type),
        )
        [res] = r_mod.reverify([finding], tmp_path)
        assert res.status == expected, (
            f"case {label}: expected {expected}, got {res.status} "
            f"(evidence={res.evidence!r})"
        )


def test_reproducer_expect_type_rejects_invalid_value():
    """expect_type must be 'either', 'file', or 'dir' — any other
    value raises at Reproducer construction time, not at fires()."""
    f_mod, _, _ = _load_oracle()
    try:
        f_mod.Reproducer(type="file_exists", path="x", expect_type="garbage")
    except ValueError as e:
        assert "expect_type" in str(e)
        return
    raise AssertionError("expected ValueError on invalid expect_type")


def test_act_on_stamps_verified_at_and_freshness_check(tmp_path, monkeypatch):
    """act_on stamps verified_at on the report; worklist_is_fresh
    returns True within TTL and False after."""
    from datetime import datetime, timezone, timedelta
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))

    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.finding", "oracle.act_on", "oracle.reverify"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.act_on import act_on, worklist_is_fresh  # noqa: E402

    findings = [
        Finding(
            skill="example", code="X", severity="info", label="doc-fix",
            description="probe",
            reproducer=Reproducer(type="manual", description="noop"),
        )
    ]
    report = act_on(findings, tmp_path)
    assert report.verified_at, "expected verified_at to be stamped"
    fresh, reason = worklist_is_fresh(report.verified_at)
    assert fresh, f"freshly-stamped worklist should be fresh: {reason}"

    past = (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat()
    fresh, reason = worklist_is_fresh(past, ttl_seconds=60)
    assert not fresh, f"1-hour-old worklist should NOT be fresh: {reason}"
    assert "TTL" in reason

    fresh, reason = worklist_is_fresh("", ttl_seconds=60)
    assert not fresh

    fresh, reason = worklist_is_fresh("not-a-timestamp", ttl_seconds=60)
    assert not fresh
    assert "ISO-8601" in reason


def test_fix_loop_regression_check_detects_introduced_finding(tmp_path):
    """verify_fix_with_regression_check returns INTRODUCED regressions
    when another finding's reproducer flips False to True across the
    fix. This is the 'fix introduced a new bug' class single-finding
    Layer D can't catch."""
    import subprocess as sp

    # -c commit.gpgsign=false defends against environments where
    # commit signing is enabled by default (e.g., the Claude Code
    # remote-execution runner sets gpg.ssh.program and user.signingkey
    # globally). Signing isn't part of what this test exercises; the
    # explicit override keeps the test green regardless of environment.
    no_sign = ["-c", "commit.gpgsign=false"]

    sp.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    sp.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)
    sp.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), check=True)
    sp.run(["git", "config", "commit.gpgsign", "false"], cwd=str(tmp_path), check=True)
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("original\n", encoding="utf-8")
    b.write_text("benign\n", encoding="utf-8")
    sp.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    sp.run(["git", *no_sign, "commit", "-q", "-m", "pre"], cwd=str(tmp_path), check=True)
    pre_sha = sp.run(
        ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    a.write_text("fixed\n", encoding="utf-8")
    b.write_text("oops-introduced-bug\n", encoding="utf-8")
    sp.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    sp.run(["git", *no_sign, "commit", "-q", "-m", "post"], cwd=str(tmp_path), check=True)
    post_sha = sp.run(
        ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.finding", "oracle.fix_loop"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.fix_loop import verify_fix_with_regression_check  # noqa: E402

    target = Finding(
        skill="x", code="A", severity="drift", label="behavior-fix",
        description="original is bad",
        reproducer=Reproducer(type="grep", command="grep -q original a.txt"),
    )
    other = Finding(
        skill="x", code="B", severity="drift", label="behavior-fix",
        description="oops phrase should never appear",
        reproducer=Reproducer(type="grep", command="grep -q oops-introduced-bug b.txt"),
    )

    result = verify_fix_with_regression_check(
        target, tmp_path, pre_sha, post_sha, [target, other]
    )
    assert result.primary.status == "VERIFIED", result.primary
    assert len(result.regressions) == 1
    assert result.regressions[0].finding.code == "B"
    assert result.regressions[0].status == "INTRODUCED"
