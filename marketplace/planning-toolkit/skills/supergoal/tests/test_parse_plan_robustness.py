"""Regression tests for parse_plan.py robustness fixes (2026-06-21).

Three parser bugs surfaced when /supergoal was run against the mega-capture plan,
a real prose-rich, brand-new-skill build plan:

  1. extract_baseline crashed (ValueError) on a sentence-final "expected 1.0."
     — the greedy [0-9.]+ ate the trailing period.
  2. extract_metric_names over-extracted ALLCAPS prose words (NOT/ALL/EVERY/F1),
     which collided with unrelated terminal docs and produced a SPURIOUS
     "27 prior arcs, REFUSED" on a brand-new skill with zero real prior arcs.
  3. extract_demo silently failed on a bold "**Demo:**" label.

These tests pin the fixes. They complement test_prior_arc_measurement.py (which
pins the recall harness); these are direct unit assertions on the failing inputs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("supergoal_parse_plan", _SCRIPTS / "parse_plan.py")
_pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pp)


# --- Fix #1: extract_baseline tolerates a trailing sentence period ---

def test_baseline_sentence_final_period_does_not_crash():
    # The exact mega-capture input that raised ValueError: could not convert '1.0.'
    got = _pp.extract_baseline("currently 0 (absent), expected 1.0.")
    assert got == {"currently_N": 0.0, "expected_M": 1.0}


def test_baseline_mid_sentence_decimal():
    got = _pp.extract_baseline("currently 0, expected 1.0 once all checks pass")
    assert got == {"currently_N": 0.0, "expected_M": 1.0}


def test_baseline_integer_and_decimal_forms():
    assert _pp.extract_baseline("currently: 5, expected: 10") == {"currently_N": 5.0, "expected_M": 10.0}
    assert _pp.extract_baseline("currently 0.825, expected 0.95") == {"currently_N": 0.825, "expected_M": 0.95}


def test_baseline_absent_returns_none():
    assert _pp.extract_baseline("no baseline numbers in this prose") is None


# --- Fix #2: extract_metric_names prefers METRIC= declarations, drops prose ALLCAPS ---

def test_declared_metric_suppresses_prose_allcaps():
    # The real emitted form: METRIC inside a print() string, amid ALLCAPS prose.
    text = ("Coverage NOT ALL EVERY F1 ACROSS THEN README\n"
            "python3 -c \"print(f'METRIC megacapture_ready={(0)/5:.2f}')\"")
    assert _pp.extract_metric_names(text) == ["megacapture_ready"]


def test_line_start_metric_declaration_form_still_works():
    assert _pp.extract_metric_names("METRIC gold_ratio=0.5") == ["gold_ratio"]


def test_fallback_allcaps_when_no_declaration():
    # No METRIC= → fallback ALLCAPS scan keeps real acronyms, drops prose words.
    got = _pp.extract_metric_names("improve F1 and MRR; do NOT regress ALL the EVERY THING")
    assert "F1" in got and "MRR" in got
    assert "NOT" not in got and "ALL" not in got and "EVERY" not in got


# --- Fix #3: extract_demo tolerates markdown emphasis on the label ---

def test_demo_bold_label():
    assert _pp.extract_demo("**Demo:** user sees X") == "user sees X"


def test_demo_plain_label():
    assert _pp.extract_demo("Demo: user sees Y") == "user sees Y"


def test_demo_italic_label():
    assert _pp.extract_demo("*Demo:* user sees Z") == "user sees Z"


def test_demo_absent_returns_none():
    assert _pp.extract_demo("no demo line here") is None
