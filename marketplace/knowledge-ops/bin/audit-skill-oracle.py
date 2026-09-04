#!/usr/bin/env python3
"""audit-skill oracle CLI — verify findings before acting on them.

Subcommands:

  reverify <findings.yaml> [--out RESULT.json] [--json] [--strict]
                            [--filter STILL-FIRES|STALE|MANUAL|ERROR]
      Layer A. Run each finding's Reproducer; classify as
      STILL-FIRES / STALE / MANUAL / ERROR. --filter restricts output
      to a single status.

  corpus check [--fixtures-root DIR] [--corpus-root DIR]
      Layer C. Run Phase 1 lint against each fixture in corpus-root
      and assert required_codes appeared / forbidden_codes did not.

  verify-fix <findings.yaml> --finding-id ID --pre-ref REF --post-ref REF
      Layer D. Run Reproducer on pre-ref and post-ref; report
      VERIFIED / STALE-PRE / FIX-INEFFECTIVE.

  ensemble <agent-0.json> <agent-1.json> ... [--min-agreement M]
      Layer B. Aggregate N agents' findings; retain ≥M-agreement.

  calibrate
      Run the calibration set and print TPR/TNR/refusal-rate per
      layer that has a calibration test.

  spec
      Print the path to SPEC.md (canonical verdict semantics).

  set-triage-status <findings> --status STATUS [--skill X] [--code Y]
                              [--desc-contains S] [--note N]
      Explicitly close findings by setting triage_status (one of
      open / STALE / FIXED / FALSE_POSITIVE / DEFER). Filter by
      skill, code, or description substring. The act_on gate skips
      findings whose triage_status is closed.

  refresh-tracker <findings>
      Re-baseline a findings YAML against the live tree. Findings
      whose reproducer now returns STALE get triage_status=STALE
      stamped automatically; already-closed findings are preserved
      as-is. Run this after a campaign wave to compact the tracker.

Every subcommand writes a TraceRecord per finding to
~/.claude/oracle-trace.jsonl (override via $AUDIT_SKILL_ORACLE_TRACE).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# oracle code lives in skills/_shared/oracle/ as of Phase 3 of the
# audit-rules lift (2026-05-26) so audit-skill and audit-rules can both
# consume it without circular-skill-import problems. sys.path insertion
# below points at the parent so `from oracle import ...` resolves.
sys.path.insert(0, str(REPO / "skills" / "_shared"))

from oracle.finding import Finding, FindingsParseError, load_findings  # noqa: E402 -- resolves via the sys.path insert above


def _load_findings_or_exit(src: Path) -> list[Finding]:
    """CLI wrapper: load findings, translate FindingsParseError into a
    clean stderr message + exit(2). Without this every CLI subcommand
    that takes a findings file would emit a raw Python traceback on
    malformed input — see /audit-skill Phase 2 category B (error paths
    must be clean)."""
    try:
        return load_findings(src)
    except (FindingsParseError, OSError) as e:
        # OSError covers FileNotFoundError/PermissionError from the
        # loader's read_text — without it a missing findings path was a
        # raw traceback (exit 1) instead of this clean error (exit 2).
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
from oracle import trace as trace_mod  # noqa: E402 -- resolves via the sys.path insert above
from oracle.act_on import act_on, format_act_on_summary  # noqa: E402 -- resolves via the sys.path insert above
from oracle.corpus import (  # noqa: E402 -- resolves via the sys.path insert above
    check_corpus_against_findings,
    check_corpus_static,
    load_corpus,
)
from oracle.discover import discover_worklist  # noqa: E402 -- resolves via the sys.path insert above
from oracle.ensemble import aggregate  # noqa: E402 -- resolves via the sys.path insert above
from oracle.fix_loop import verify_fix_against_refs  # noqa: E402 -- resolves via the sys.path insert above
from oracle.report import build_report, render_json, render_markdown  # noqa: E402 -- resolves via the sys.path insert above
from oracle.reverify import format_results, reverify  # noqa: E402 -- resolves via the sys.path insert above
from oracle.tracker import convert_tracker_to_yaml  # noqa: E402 -- resolves via the sys.path insert above
from oracle.validate import format_rejections, validate_for_dispatch  # noqa: E402 -- resolves via the sys.path insert above


def cmd_reverify(args):
    src = Path(args.findings)
    if not src.exists():
        print(f"error: findings file not found: {src}", file=sys.stderr)
        return 2
    findings = _load_findings_or_exit(src)
    results = reverify(findings, REPO)
    if args.filter:
        results = [r for r in results if r.status == args.filter]

    if args.json:
        out = [
            {
                "skill": r.finding.skill,
                "code": r.finding.code,
                "label": r.finding.label,
                "status": r.status,
                "evidence": r.evidence,
                "description": r.finding.description,
            }
            for r in results
        ]
        print(json.dumps(out, indent=2))
    else:
        print(format_results(results))

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            json.dumps(
                [
                    {
                        "skill": r.finding.skill,
                        "code": r.finding.code,
                        "status": r.status,
                        "evidence": r.evidence,
                    }
                    for r in results
                ],
                indent=2,
            ),
            encoding="utf-8",
        )

    # Exit 1 if any STILL-FIRES or ERROR (something needs attention).
    any_action = any(r.status in ("STILL-FIRES", "ERROR") for r in results)
    return 1 if any_action and args.strict else 0


def cmd_verify_fix(args):
    findings = _load_findings_or_exit(Path(args.findings))
    target = next((f for f in findings
                   if trace_mod.finding_id(f.skill, f.code, f.description) == args.finding_id),
                  None)
    if target is None:
        print(f"Finding id {args.finding_id!r} not found in {args.findings}",
              file=sys.stderr)
        return 2
    result = verify_fix_against_refs(target, REPO, args.pre_ref, args.post_ref)
    print(f"{result.status}: pre_fires={result.pre_fires} post_fires={result.post_fires}")
    print(f"  evidence_pre:  {result.evidence_pre}")
    print(f"  evidence_post: {result.evidence_post}")
    return 0 if result.status == "VERIFIED" else 1


def cmd_corpus_check(args):
    corpus_root = Path(args.corpus_root) if args.corpus_root else \
        REPO / "skills" / "audit-skill" / "tests" / "golden-findings"
    fixtures_root = Path(args.fixtures_root) if args.fixtures_root else \
        REPO / "skills" / "audit-skill" / "tests" / "fixtures"
    corpus = load_corpus(corpus_root)
    if not corpus:
        print(f"No corpus entries under {corpus_root}", file=sys.stderr)
        return 1

    # Static check first.
    errors = check_corpus_static(corpus, fixtures_root)
    if errors:
        print("CORPUS STATIC ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 2

    if args.static_only:
        print(f"Corpus OK ({len(corpus)} entries; static check only).")
        return 0

    # Live check: run Phase 1 audit against each fixture and compare.
    # We import the audit module directly rather than shell out.
    import importlib.util
    spec = importlib.util.spec_from_file_location("audit_skill",
                                                    REPO / "bin" / "audit-skill.py")
    audit_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_mod)

    findings_by_fixture: dict[str, list[str]] = {}
    original_skills = audit_mod.SKILLS
    try:
        audit_mod.SKILLS = fixtures_root
        # Warm the known-tools cache by pointing at the canonical tree first.
        canon_entry = None
        try:
            audit_mod.SKILLS = REPO / "skills"
            canon_entry = audit_mod._load_known_tools()
        except Exception:  # noqa: S110, BLE001 -- fail-open: cache warm-up is optional; canon_entry stays None
            pass  # optional warm-up; canon_entry stays None
        for entry in corpus:
            audit_mod.SKILLS = fixtures_root
            if canon_entry is not None:
                audit_mod._KNOWN_TOOLS_CACHE[str(fixtures_root)] = canon_entry
            try:
                f_list = audit_mod.audit(entry.fixture)
            except Exception as e:
                print(f"audit failed on fixture {entry.fixture!r}: {e}", file=sys.stderr)
                f_list = []
            findings_by_fixture[entry.fixture] = [f.code for f in f_list]
    finally:
        audit_mod.SKILLS = original_skills
        audit_mod._KNOWN_TOOLS_CACHE = {}

    results = check_corpus_against_findings(corpus, findings_by_fixture)
    any_fail = False
    for r in results:
        if r.ok:
            print(f"PASS  {r.fixture}")
        else:
            any_fail = True
            print(f"FAIL  {r.fixture}")
            if r.missing_required:
                print(f"        missing required codes: {r.missing_required}")
            if r.found_forbidden:
                print(f"        observed forbidden codes: {r.found_forbidden}")
    return 1 if any_fail else 0


def cmd_ensemble(args):
    agent_findings = [_load_findings_or_exit(Path(p)) for p in args.agent_files]
    consensus = aggregate(agent_findings,
                          min_agreement=args.min_agreement,
                          similarity_threshold=args.similarity_threshold)
    if args.json:
        out = []
        for c in consensus:
            out.append({
                "skill": c.representative.skill,
                "code": c.representative.code,
                "agent_count": c.agent_count,
                "n_total": c.n_total,
                "confidence": c.confidence,
                "description": c.representative.description,
            })
        print(json.dumps(out, indent=2))
    else:
        for c in consensus:
            print(f"{c.agent_count}/{c.n_total} confidence={c.confidence:.2f} "
                  f"{c.representative.skill}/{c.representative.code} "
                  f"{c.representative.description[:60]}")
    return 0


def cmd_calibrate(args):
    """Re-run the calibration test and print the numbers."""
    import subprocess
    test_path = REPO / "skills" / "audit-skill" / "tests" / "test_oracle_calibration.py"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-q", "-s",
         "-k", "calibration_tpr_tnr"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    print(r.stdout)
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    return r.returncode


def cmd_spec(args):
    spec_path = REPO / "skills" / "_shared" / "oracle" / "SPEC.md"
    print(spec_path)
    return 0


def cmd_act_on(args):
    """Pre-action gate: reverify findings, drop STALE, emit filtered
    worklist. The fix-orchestrator workflow MUST call this immediately
    before dispatching any fix-batch — otherwise stale findings consume
    fix budget redundantly (the 38% stale rate observed in the May 2026
    campaign was the motivation for adding this gate).

    Input: a findings YAML / JSON, OR a markdown tracker (path ending
    in .md). For markdown trackers, this command first converts to
    YAML in-place at <tracker>.findings.yaml, then reverifies.

    Also enforces the Phase 2 label/reproducer contract (`type: manual`
    ⟺ `label: unverified`) unless --skip-contract-check is passed.
    Contract violations are dispatch-unsafe: they route auto-fix-batches
    to findings the oracle hasn't actually verified.
    """
    src = Path(args.findings)
    if not src.exists():
        print(f"error: input file not found: {src}", file=sys.stderr)
        return 2
    if src.suffix == ".md":
        # Markdown tracker — convert first.
        yaml_path = src.with_suffix(".findings.yaml")
        count = convert_tracker_to_yaml(src, yaml_path)
        print(f"converted markdown tracker → {yaml_path} ({count} findings)",
              file=sys.stderr)
        findings = _load_findings_or_exit(yaml_path)
    else:
        findings = _load_findings_or_exit(src)

    # Optional scoping: batch campaigns dispatch one class/skill-set at a
    # time. Previously this required an ad-hoc filter script between
    # act-on and dispatch (campaign 11 carried one through three batches).
    skills_filter = set(getattr(args, "skill", None) or [])
    codes_filter = set(getattr(args, "code", None) or [])
    if skills_filter or codes_filter:
        before = len(findings)
        findings = [
            f for f in findings
            if (not skills_filter or f.skill in skills_filter)
            and (not codes_filter or f.code in codes_filter)
        ]
        print(
            f"filter: {before} → {len(findings)} findings "
            f"(skill={sorted(skills_filter) or 'any'}, "
            f"code={sorted(codes_filter) or 'any'})",
            file=sys.stderr,
        )

    # Contract gate: refuse to emit a worklist when actionable findings
    # violate the label/reproducer pairing. Skippable via flag for
    # forensic debugging on legacy trackers, but the default is strict.
    if not args.skip_contract_check:
        manual_not_unverified, auto_but_unverified = _contract_violations(findings)
        total_violations = len(manual_not_unverified) + len(auto_but_unverified)
        if total_violations > 0:
            print(
                f"\nERROR: act-on refused; contract violations in input "
                f"({total_violations} of {len(findings)} findings)",
                file=sys.stderr,
            )
            if manual_not_unverified:
                print(f"  MANUAL_NOT_UNVERIFIED ({len(manual_not_unverified)}): "
                      f"manual reproducer paired with doc-fix/behavior-fix label",
                      file=sys.stderr)
                for f in manual_not_unverified[:3]:
                    print(f"    {f.skill}/{f.code} [{f.label}]: "
                          f"{f.description[:70]}",
                          file=sys.stderr)
                if len(manual_not_unverified) > 3:
                    print(f"    ... and {len(manual_not_unverified) - 3} more",
                          file=sys.stderr)
            if auto_but_unverified:
                print(f"  AUTO_BUT_UNVERIFIED ({len(auto_but_unverified)}): "
                      f"auto reproducer paired with unverified label",
                      file=sys.stderr)
            print(
                "\nFix: run skills/audit-skill/scripts/backfill_reproducers.py "
                "on the input, OR pass --skip-contract-check to override "
                "(forensic mode; not safe for fix-batch dispatch).",
                file=sys.stderr,
            )
            return 1

    report = act_on(findings, REPO)
    print(format_act_on_summary(report), file=sys.stderr)

    # Advisory reproducer-smell warnings (deployed-path probes, stateful
    # appends) — never gate, but surface BEFORE dispatch instead of at
    # verdict-forensics time (2026-06-12 campaign lesson).
    from oracle.validate import advisory_warnings
    warns = advisory_warnings(report.worklist)
    if warns:
        print(f"\nadvisory warnings ({len(warns)}):", file=sys.stderr)
        for w in warns:
            print(f"  {w}", file=sys.stderr)

    # Emit the worklist to args.out (YAML) — what the fix-orchestrator
    # then dispatches against. With --auto-only, emit ONLY the
    # STILL-FIRES subset: MANUAL findings fail validate_worklist.py
    # Gate 1 and ERROR findings fail Gate 4, so a bare worklist that
    # includes them is not dispatchable as written (2026-08-22
    # campaign-11 close-out: 1 STILL-FIRES + 33 MANUAL emitted, then
    # rejected by the skill's own Step-0 gates).
    if args.out:
        from oracle.act_on import dispatchable_only
        from oracle.tracker import _to_yaml
        emit_list = report.worklist
        if getattr(args, "auto_only", False):
            emit_list = dispatchable_only(report)
            dropped = len(report.worklist) - len(emit_list)
            if dropped:
                print(f"--auto-only: dropped {dropped} MANUAL/ERROR "
                      f"finding(s) from the emitted worklist (they remain "
                      f"in the tracker for human review)", file=sys.stderr)
        out_path = Path(args.out)
        out_path.write_text(_to_yaml(emit_list), encoding="utf-8")
        print(f"\nworklist → {out_path} ({len(emit_list)} findings to dispatch)",
              file=sys.stderr)

    # Exit code: 0 if there's actionable work, 0 if all stale (nothing
    # left), 1 if the reproducer itself errored on any finding (an
    # instrument problem the caller must address before continuing).
    # With --auto-only the ERROR findings were deliberately EXCLUDED
    # from the emitted worklist, so they don't block dispatch — report
    # them and exit 0 (the emitted worklist is dispatchable as-is).
    if report.error:
        if getattr(args, "auto_only", False):
            print(f"\n{len(report.error)} reproducer ERROR(s) excluded from "
                  f"the worklist — repair them for a future batch",
                  file=sys.stderr)
            return 0
        print(f"\n{len(report.error)} reproducer ERROR(s) — fix these before "
              f"acting on the worklist", file=sys.stderr)
        return 1
    return 0


def _contract_violations(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Return (manual_not_unverified, auto_but_unverified) for actionable
    findings. Shared logic between cmd_contract_check and cmd_act_on so
    the gate semantics stay aligned."""
    mnu: list[Finding] = []
    abu: list[Finding] = []
    for f in findings:
        if not f.is_actionable():
            continue
        is_manual = (f.reproducer.type == "manual")
        is_unverified = (f.label == "unverified")
        if is_manual and not is_unverified:
            mnu.append(f)
        elif not is_manual and is_unverified:
            abu.append(f)
    return mnu, abu


def cmd_convert_tracker(args):
    """One-shot: convert a markdown tracker to YAML findings without
    running reverify. Useful for inspecting what the parser produced."""
    src = Path(args.tracker)
    if not src.exists():
        print(f"error: tracker file not found: {src}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else src.with_suffix(".findings.yaml")
    count = convert_tracker_to_yaml(src, out)
    print(f"{src} → {out}: {count} findings parsed")
    return 0


def cmd_validate(args):
    """Root-cause fix for causes 3 + 6 (skippable gate, prose findings).

    The fix-orchestrator API MUST call this before dispatching any
    fix-batch. Rejections:
      REJECT_PROSE_INPUT — raw markdown tracker (run act-on first)
      REJECT_NO_REPRODUCER — finding has type=manual
      REJECT_NOT_REVERIFIED — no trace record (act-on not run)
      REJECT_STALE_RECORD — trace older than TTL (default 30 min)

    Exits 0 if dispatchable, 1 if rejected (so CI / orchestrators
    can gate dispatch on the exit code)."""
    rejections = validate_for_dispatch(
        Path(args.worklist),
        max_reverify_age_seconds=args.max_age_seconds,
        repo_root=REPO,
    )
    print(format_rejections(rejections))
    # Advisory smells (deployed-path probes, stateful appends) — printed,
    # never gating. See oracle.validate.advisory_warnings.
    try:
        findings = load_findings(Path(args.worklist))
    except FindingsParseError:
        findings = []
    from oracle.validate import advisory_warnings
    warns = advisory_warnings(findings)
    if warns:
        print(f"\nadvisory warnings ({len(warns)}):")
        for w in warns:
            print(f"  {w}")
    return 0 if not rejections else 1


def cmd_specificity_check(args):
    """Specificity guard (Layer A hardening): classify each finding's
    reproducer as SPECIFIC / NONSPECIFIC_STATIC / NONSPECIFIC_CONTROL.

    A non-specific reproducer (e.g. `grep -q .`) fires regardless of
    repository content, so its STILL-FIRES verdict certifies nothing —
    the proposer-grades-its-own-homework reward-hacking class. Exits 1
    under --strict if any non-specific reproducer is found."""
    from oracle.specificity import is_nonspecific, specificity_verdict
    findings = _load_findings_or_exit(Path(args.findings))
    nonspecific = 0
    for f in findings:
        if f.reproducer.type == "manual":
            print(f"SKIP      {f.skill}/{f.code}  (manual reproducer)")
            continue
        verdict, ev = specificity_verdict(f.reproducer, REPO)
        if is_nonspecific(verdict):
            nonspecific += 1
            print(f"NONSPEC   {f.skill}/{f.code}  {verdict}: {ev}")
        else:
            print(f"SPECIFIC  {f.skill}/{f.code}")
    print(f"\n{nonspecific} non-specific / {len(findings)} findings")
    if args.strict and nonspecific:
        return 1
    return 0


def cmd_profile(args):
    """Print the per-layer profile vector (soundness / FP / FN / cost /
    automation / groundedness + derived tier) — the corrected framework's
    replacement for the monotonic Tier ladder. SPEC.md §"Layer profiles"
    is the prose mirror; oracle/profile.py is the source of truth."""
    from oracle.profile import render_profiles
    print(render_profiles(args.format))
    return 0


def cmd_ensemble_dispatch(args):
    """Layer B cross-vendor (in-process, OPT-IN, never CI): dispatch an
    audit prompt to the anthropic/openai/xai adapters, parse each vendor's
    findings, and aggregate. Degrades to available vendors (missing API
    keys are recorded, not fatal). Writes per-vendor Layer-B trace records.
    NOT a sound oracle — cross-vendor judges still co-err; use as a
    pre-filter composed with Layer A (see SPEC §'Layer B')."""
    from oracle.ensemble import distinct_vendor_count
    from oracle.ensemble_dispatch import ensemble_cross_vendor
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        prompt = args.prompt or ""
    if not prompt.strip():
        print("error: provide --prompt or --prompt-file", file=sys.stderr)
        return 2
    vendors = [v.strip() for v in args.vendors.split(",")] if args.vendors else None
    consensus, vendors_used = ensemble_cross_vendor(
        prompt, args.skill, vendors=vendors, min_agreement=args.min_agreement)
    print(f"vendors_used: {vendors_used or '(none — no API keys present?)'}")
    print(f"consensus findings (>= M agreement): {len(consensus)}")
    for cf in consensus:
        print(f"  [{cf.agent_count}/{cf.n_total}, {distinct_vendor_count(cf)} vendor(s): "
              f"{','.join(cf.vendors) or '-'}] {cf.representative.skill}/"
              f"{cf.representative.code}: {cf.representative.description[:80]}")
    return 0


def cmd_discover(args):
    """Root-cause fix for cause 1 (static tracker / live-tree mismatch).

    Runs Phase 1 (mechanical lint) inline + Layer A reverify in one
    shot. The output worklist has a trace record per finding right
    now, so it passes validate-for-dispatch immediately. The
    orchestrator never sees a stale tracker because there is no
    tracker — discovery and verification are the same call.

    Optionally accepts a Phase 2 findings file (from prior agent
    dispatch) and merges those into the worklist before reverify."""
    repo_root = REPO
    phase2_findings = []
    if args.phase2:
        phase2_findings = _load_findings_or_exit(Path(args.phase2))
    report = discover_worklist(repo_root, args.skill, phase2_findings)
    print(format_act_on_summary(report))
    if args.out:
        from oracle.tracker import _to_yaml
        Path(args.out).write_text(_to_yaml(report.worklist), encoding="utf-8")
        print(f"\nworklist → {args.out} ({len(report.worklist)} findings)")
    return 0 if not report.error else 1


def cmd_set_triage_status(args):
    """Set or clear triage_status on one or more findings in a YAML file.

    Matches findings by (skill, code, optional description-substring).
    A finding matches if ALL of these are true:
      - finding.skill == args.skill (if provided)
      - finding.code == args.code (if provided)
      - args.desc_contains is a substring of finding.description (if provided)

    Writes the updated YAML in place. Exit 0 if at least one finding was
    updated, exit 2 if no findings matched (likely a typo or stale spec).
    """
    from oracle.finding import TRIAGE_STATUSES
    from oracle.tracker import update_triage_surgical

    src = Path(args.findings)
    if not src.exists():
        print(f"error: findings file not found: {src}", file=sys.stderr)
        return 2
    if args.status not in TRIAGE_STATUSES:
        print(f"error: status must be one of {TRIAGE_STATUSES}; got {args.status!r}",
              file=sys.stderr)
        return 2
    findings = _load_findings_or_exit(src)
    # Findings are loaded ONLY to compute the match set; the write goes
    # through line-level surgical edits so a triage update can never
    # reformat (or drop fields from) the other N-1 findings — the full
    # _to_yaml re-emit this replaces deleted all 451 location: fields in
    # one call on 2026-06-12.
    match_indices = []
    for i, f in enumerate(findings):
        if args.skill and f.skill != args.skill:
            continue
        if args.code and f.code != args.code:
            continue
        if args.desc_contains and args.desc_contains not in f.description:
            continue
        match_indices.append(i)
    if not match_indices:
        print(f"no findings matched the filter (skill={args.skill!r}, "
              f"code={args.code!r}, desc_contains={args.desc_contains!r})",
              file=sys.stderr)
        return 2
    try:
        matched = update_triage_surgical(
            src, match_indices, args.status, note=args.note or None)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"set triage_status={args.status} on {matched} finding(s) in {src}")
    return 0


def cmd_refresh_tracker(args):
    """Re-baseline a findings YAML against the live tree.

    For each finding, runs Layer A reverify. If the reproducer fires
    STALE, sets triage_status=STALE (preserving any existing more-
    specific status like FIXED / DEFER / FALSE_POSITIVE). Leaves
    actionable findings as-is.

    Use this at the END of a campaign wave (or before the next wave
    starts) to compact the tracker — previously-real findings that
    have since been resolved get explicitly closed in the YAML, so
    the next operator doesn't have to re-triage them by hand.

    Designed for the failure mode observed in the 2026-05-25 triage:
    21 of 25 [unverified] findings turned out to be stale after the
    campaign, but the YAML had no record of it; manual triage was
    needed to filter them.
    """
    from oracle.reverify import reverify
    from oracle.tracker import _to_yaml

    src = Path(args.findings)
    if not src.exists():
        print(f"error: findings file not found: {src}", file=sys.stderr)
        return 2
    findings = _load_findings_or_exit(src)
    # Only re-evaluate findings that don't already have a closed status
    # (don't clobber operator-set FIXED / DEFER / FALSE_POSITIVE).
    actionable = [f for f in findings if f.is_actionable()]
    other = [f for f in findings if not f.is_actionable()]
    print(f"refreshing {len(actionable)} actionable finding(s) "
          f"({len(other)} already triage-closed)", file=sys.stderr)

    results = reverify(actionable, REPO)
    by_id = {(r.finding.skill, r.finding.code, r.finding.description): r
             for r in results}

    n_newly_stale = 0
    n_still_fires = 0
    n_manual = 0
    n_error = 0
    for f in actionable:
        r = by_id.get((f.skill, f.code, f.description))
        if r is None:
            continue
        if r.status == "STALE":
            f.triage_status = "STALE"
            if not f.triage_note:
                f.triage_note = (f"reverify {r.status} on {Path(__file__).name} refresh-tracker; "
                                 f"evidence: {r.evidence[:140]}")
            n_newly_stale += 1
        elif r.status == "STILL-FIRES":
            n_still_fires += 1
        elif r.status == "MANUAL":
            n_manual += 1
        elif r.status == "ERROR":
            n_error += 1

    src.write_text(_to_yaml(findings), encoding="utf-8")
    print(f"  newly STALE:        {n_newly_stale} (triage_status set)")
    print(f"  STILL-FIRES:        {n_still_fires} (kept as actionable)")
    print(f"  MANUAL:             {n_manual} (no automated check; left as-is)")
    print(f"  ERROR:              {n_error} (reproducer broken; left as-is)")
    print(f"  already triage-closed: {len(other)}")
    print(f"\ntracker updated: {src}")
    return 0 if n_error == 0 else 1


def cmd_contract_check(args):
    """Phase 2 contract: type=manual reproducer ⟺ label=unverified.

    The Phase 2 prompt template (oracle/templates/phase2-prompt.md)
    requires this pairing. Agents sometimes emit findings with
    type=manual but label=doc-fix or behavior-fix, which routes them
    to the fix-batch instead of human review — undermining the gate.

    Two violation classes:

      MANUAL_NOT_UNVERIFIED: reproducer is type=manual but label is
        doc-fix or behavior-fix. The oracle cannot verify; the
        finding must be either upgraded to an auto-checkable
        reproducer OR labeled unverified.

      AUTO_BUT_UNVERIFIED: reproducer is non-manual but label is
        unverified. The auto-check is the verification; the label
        should be doc-fix or behavior-fix per the reproducer's
        evidence.

    Exit 0 if no violations or --strict not set. Exit 1 if --strict
    and any violations.
    """
    src = Path(args.findings)
    findings = _load_findings_or_exit(src)
    manual_not_unverified, auto_but_unverified = _contract_violations(findings)

    total = len(manual_not_unverified) + len(auto_but_unverified)
    print(f"contract-check: {total} violation(s) across {len(findings)} finding(s)")
    if manual_not_unverified:
        print(f"\n  MANUAL_NOT_UNVERIFIED ({len(manual_not_unverified)}):")
        print("    Reproducer is type=manual but label is not 'unverified'.")
        print("    Fix: either supply an auto-checkable reproducer OR change label to unverified.")
        print("    Recommended: run skills/audit-skill/scripts/backfill_reproducers.py")
        for f in manual_not_unverified[:5]:
            print(f"      {f.skill}/{f.code} [{f.label}]: {f.description[:80]}")
        if len(manual_not_unverified) > 5:
            print(f"      ... and {len(manual_not_unverified) - 5} more")
    if auto_but_unverified:
        print(f"\n  AUTO_BUT_UNVERIFIED ({len(auto_but_unverified)}):")
        print("    Reproducer is auto-checkable but label is 'unverified'.")
        print("    Fix: change label to doc-fix or behavior-fix.")
        for f in auto_but_unverified[:5]:
            print(f"      {f.skill}/{f.code} [{f.label}]: {f.description[:80]}")
        if len(auto_but_unverified) > 5:
            print(f"      ... and {len(auto_but_unverified) - 5} more")
    if total == 0:
        print("  (contract OK)")
    if args.strict and total > 0:
        return 1
    return 0


def cmd_report(args):
    """Phase 4: bundle Phase 1 + Phase 2/3-survived findings into a
    single actionable report. At least one of --phase1 / --phase2 is
    required. Output is markdown by default; --format json emits the
    same data structured for programmatic consumers.

    Closes the prose-assembly gap called out in the 2026-05-27
    audit-skill self-assessment: the procedure ends in 'combine
    findings into one numbered list' but the bundling was previously
    left to the calling agent.
    """
    p1 = Path(args.phase1) if args.phase1 else None
    p2 = Path(args.phase2) if args.phase2 else None
    if p1 is None and p2 is None:
        print("error: at least one of --phase1 / --phase2 is required",
              file=sys.stderr)
        return 2
    for label, path in (("phase1", p1), ("phase2", p2)):
        if path is not None and not path.exists():
            print(f"error: {label} input not found: {path}", file=sys.stderr)
            return 2
    try:
        entries, header = build_report(phase1_path=p1, phase2_path=p2)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.format == "json":
        out = render_json(entries, header)
    else:
        out = render_markdown(entries, header)

    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"report → {args.out} ({len(entries)} findings)", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


def main(argv=None):
    # Windows stdout/stderr default to cp1252, which raises UnicodeEncodeError
    # on the non-ASCII characters in this CLI's help text and finding
    # descriptions (e.g. U+2265 "≥" in the subcommand docs). Reconfigure to
    # UTF-8 so --help, --json, and error output never crash. This is the
    # stdout analog of platform-constraints.md python_open_always_utf8; the
    # "skip reconfigure in throwaway scripts" exception does not apply because
    # this is production Phase-3 tooling invoked by /audit-skill.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass  # already-wrapped or non-reconfigurable stream
    p = argparse.ArgumentParser(prog="audit-skill-oracle", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_re = sub.add_parser("reverify", help="Layer A: re-verify findings")
    p_re.add_argument("findings", help="path to findings.yaml or findings.json")
    p_re.add_argument("--out", help="write JSON result to this path")
    p_re.add_argument("--json", action="store_true", help="emit JSON to stdout")
    p_re.add_argument("--filter",
                       choices=["STILL-FIRES", "STALE", "MANUAL", "ERROR"],
                       help="only show results with this status (text + JSON output paths)")
    p_re.add_argument("--strict", action="store_true",
                       help="exit 1 if any STILL-FIRES or ERROR")
    p_re.set_defaults(func=cmd_reverify)

    p_fix = sub.add_parser("verify-fix", help="Layer D: pre/post-fix verification")
    p_fix.add_argument("findings", help="findings.yaml containing the target finding")
    p_fix.add_argument("--finding-id", required=True,
                        help="hash from oracle.trace.finding_id()")
    p_fix.add_argument("--pre-ref", required=True, help="git ref before the fix")
    p_fix.add_argument("--post-ref", required=True, help="git ref after the fix")
    p_fix.set_defaults(func=cmd_verify_fix)

    p_co = sub.add_parser("corpus", help="Layer C: golden-fixture regression")
    co_sub = p_co.add_subparsers(dest="corpus_cmd", required=True)
    p_co_check = co_sub.add_parser("check")
    p_co_check.add_argument("--corpus-root", help="override default corpus dir")
    p_co_check.add_argument("--fixtures-root", help="override default fixtures dir")
    p_co_check.add_argument("--static-only", action="store_true",
                             help="skip live audit; only validate corpus YAML schema")
    p_co_check.set_defaults(func=cmd_corpus_check)

    p_en = sub.add_parser("ensemble", help="Layer B: aggregate N-agent findings")
    p_en.add_argument("agent_files", nargs="+", help="one JSON/YAML per agent")
    p_en.add_argument("--min-agreement", type=int, default=None,
                       help="minimum agents that must agree (default: majority)")
    p_en.add_argument("--similarity-threshold", type=float, default=0.4,
                       help="Jaccard token overlap threshold (default 0.4)")
    p_en.add_argument("--json", action="store_true")
    p_en.set_defaults(func=cmd_ensemble)

    p_ca = sub.add_parser("calibrate", help="run TPR/TNR calibration test")
    p_ca.set_defaults(func=cmd_calibrate)

    p_sp = sub.add_parser("spec", help="print path to SPEC.md")
    p_sp.set_defaults(func=cmd_spec)

    p_ao = sub.add_parser(
        "act-on",
        help="pre-action gate: reverify + drop stale + emit worklist "
             "(MANDATORY before any fix-batch dispatch)",
    )
    p_ao.add_argument("findings",
                       help="findings.yaml | findings.json | markdown tracker (.md)")
    p_ao.add_argument("--out", required=True,
                       help="path to write filtered worklist YAML (what fix-batches dispatch against)")
    p_ao.add_argument(
        "--auto-only", action="store_true", dest="auto_only",
        help="emit ONLY STILL-FIRES findings to --out (drop MANUAL/ERROR, "
             "which fail the /audit-fix Step-0 dispatch gates); the summary "
             "still reports every category")
    p_ao.add_argument(
        "--skip-contract-check", action="store_true",
        help=(
            "skip the label/reproducer contract check. Forensic mode "
            "only — the resulting worklist is NOT safe for fix-batch "
            "dispatch because manual reproducers may be paired with "
            "actionable labels."
        ),
    )
    p_ao.add_argument("--skill", action="append", default=None,
                       help="filter: only findings for this skill (repeatable)")
    p_ao.add_argument("--code", action="append", default=None,
                       help="filter: only findings with this code, e.g. A1/B/D4 (repeatable)")
    p_ao.set_defaults(func=cmd_act_on)

    p_ct = sub.add_parser(
        "convert-tracker",
        help="convert a markdown findings tracker to YAML (no reverify)",
    )
    p_ct.add_argument("tracker", help="path to AUDIT-TRACKERS/*.md")
    p_ct.add_argument("--out", help="output YAML path (default: <tracker>.findings.yaml)")
    p_ct.set_defaults(func=cmd_convert_tracker)

    p_va = sub.add_parser(
        "validate",
        help="schema enforcement at the fix-orchestrator boundary (root-cause fix)",
    )
    p_va.add_argument("worklist", help="path to worklist.yaml")
    p_va.add_argument("--max-age-seconds", type=int, default=1800,
                       help="reject worklists older than this (default 1800 = 30 min)")
    p_va.set_defaults(func=cmd_validate)

    p_di = sub.add_parser(
        "discover",
        help="root-cause fix for static-tracker problem — discovery + reverify in one shot",
    )
    p_di.add_argument("--skill", help="single skill to discover (default: --all)")
    p_di.add_argument("--phase2", help="optional path to Phase 2 agent findings YAML to merge")
    p_di.add_argument("--out", help="path to write verified worklist YAML")
    p_di.set_defaults(func=cmd_discover)

    p_ts = sub.add_parser(
        "set-triage-status",
        help="set triage_status on findings matching (skill, code, description-substring)",
    )
    p_ts.add_argument("findings", help="path to findings YAML")
    p_ts.add_argument("--status", required=True,
                       choices=["open", "STALE", "FIXED", "FALSE_POSITIVE", "DEFER"],
                       help="triage status to assign")
    p_ts.add_argument("--skill", help="filter: only findings with this skill name")
    p_ts.add_argument("--code", help="filter: only findings with this code (e.g., D2, A1)")
    p_ts.add_argument("--desc-contains",
                       help="filter: only findings whose description contains this substring")
    p_ts.add_argument("--note", help="optional triage_note (rationale)")
    p_ts.set_defaults(func=cmd_set_triage_status)

    p_rt = sub.add_parser(
        "refresh-tracker",
        help="re-baseline findings YAML against live tree (auto-set STALE on non-firing findings)",
    )
    p_rt.add_argument("findings", help="path to findings YAML to refresh in place")
    p_rt.set_defaults(func=cmd_refresh_tracker)

    p_cc = sub.add_parser(
        "contract-check",
        help=(
            "check the Phase 2 label/reproducer contract: manual reproducers "
            "must pair with label=unverified. Non-manual reproducers should "
            "carry a non-unverified label."
        ),
    )
    p_cc.add_argument("findings", help="path to findings YAML")
    p_cc.add_argument(
        "--strict", action="store_true",
        help="exit non-zero on any contract violation (default: report only)",
    )
    p_cc.set_defaults(func=cmd_contract_check)

    p_spc = sub.add_parser(
        "specificity-check",
        help=(
            "specificity guard: flag vacuous reproducers (e.g. `grep -q .`) "
            "that fire regardless of content — the proposer-grades-its-own-"
            "homework class. --strict exits 1 on any non-specific finding."
        ),
    )
    p_spc.add_argument("findings", help="path to findings YAML/JSON")
    p_spc.add_argument("--strict", action="store_true",
                        help="exit 1 if any non-specific reproducer is found")
    p_spc.set_defaults(func=cmd_specificity_check)

    p_pf = sub.add_parser(
        "profile",
        help="print the per-layer profile vector (replaces the Tier ladder)",
    )
    p_pf.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p_pf.set_defaults(func=cmd_profile)

    p_ed = sub.add_parser(
        "ensemble-dispatch",
        help="Layer B cross-vendor (opt-in, in-process; needs API keys, degrades gracefully)",
    )
    p_ed.add_argument("--skill", required=True, help="skill under audit (tags findings + trace)")
    p_ed.add_argument("--prompt", help="inline audit prompt")
    p_ed.add_argument("--prompt-file", help="path to a file containing the audit prompt")
    p_ed.add_argument("--vendors", help="comma-separated subset of anthropic,openai,xai (default: all)")
    p_ed.add_argument("--min-agreement", type=int, default=None,
                       help="minimum vendors that must agree (default: majority)")
    p_ed.set_defaults(func=cmd_ensemble_dispatch)

    p_rp = sub.add_parser(
        "report",
        help=(
            "Phase 4: bundle Phase 1 NDJSON + Phase 2/3 worklist YAML "
            "into a single numbered report (markdown or JSON)."
        ),
    )
    p_rp.add_argument("--phase1", help="Phase 1 NDJSON path (audit-skill.py --ndjson=)")
    p_rp.add_argument("--phase2", help="Phase 2/3 worklist YAML (oracle act-on --out)")
    p_rp.add_argument("--out", help="write report to this path (default: stdout)")
    p_rp.add_argument("--format", choices=["markdown", "json"], default="markdown",
                       help="output format (default markdown)")
    p_rp.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
