"""Tests for bin/dynamic_rules.py — fixtures are VERBATIM rule shapes from the
2026-08-28 dept-rename incident (the inputs that actually broke or nearly broke),
per tdd-mutation-testing item 18: real breaking inputs, not synthesized lookalikes."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

from dynamic_rules import (  # noqa: E402
    build_rewrite_plan,
    dedupe_duplicate_or_clauses,
    exact_literals,
    extract_comparisons,
    fuzzy_comparisons,
    hotfix_eligible_values,
    match_set,
    match_set_delta,
    op_matches,
    rewrite_exact_literals,
    top_level_or_defect,
)

# Verbatim live rules (2026-08-28):
GUARDED = ('(user.department -eq "Software") and (user.employeeId -ne "Contractor") '
           'and (user.accountEnabled -eq True) and (user.userType -eq "Member")')
# Dynamic_Software after the portal hotfix appended an UNGUARDED or-clause:
HOTFIXED_TRAILING = GUARDED + ' or (user.department -eq "Software Eng")'
# Dynamic_HardwareEngineering: hotfix added INSIDE the guarded paren group:
HW_IN_PAREN = ('((user.department -eq "Hardware Engineering") or (user.department -eq "Hardware Eng") '
               'or (user.department -eq "Mech Eng") or (user.department -eq "Elec Eng")) '
               'and (user.accountEnabled -eq true) and (user.userType -eq "Member") '
               'and (user.employeeId -ne "Contractor")')
# Helm IT Portal - Users: PowerShell-style -or/-and joiners, live in the tenant:
HELM = ('((user.department -eq "Information Technology") -or (user.jobTitle -eq "Network Engineer")) '
        '-and (user.accountEnabled -eq true) -and (user.userType -eq "Member")')
# Dynamic_IT: the 2026-08-14 documented top-level-or precedence defect:
DYNAMIC_IT = ('(user.department -eq "Information Technology") and (user.employeeId -ne "Contractor") '
              'and (user.accountEnabled -eq True) and (user.userType -eq "Member") '
              'or (user.jobTitle -eq "Network Engineer")')
IN_ARRAY = '(user.department -in ["Bus Dev","Gov Relations"]) and (user.accountEnabled -eq true)'
EM_FRAGMENT = ('(user.accountEnabled -eq true) and (user.department -ne "Contractor") and '
               '((user.jobTitle -contains "Responsible Engineer") or '
               '((user.department -contains "Engineer") and (user.jobTitle -contains "Project Manager")))')


class TestExtraction(unittest.TestCase):
    def test_guarded_chain_extracts_department_only(self):
        self.assertEqual(extract_comparisons(GUARDED, "department"), [("eq", "Software")])
        # employeeId comparison is a different attr — must not leak in
        self.assertEqual(extract_comparisons(GUARDED, "employeeId"), [("ne", "Contractor")])

    def test_in_array_literals(self):
        self.assertEqual(extract_comparisons(IN_ARRAY, "department"),
                         [("in", "Bus Dev"), ("in", "Gov Relations")])

    def test_hyphenated_joiners_do_not_break_extraction(self):
        self.assertEqual(exact_literals(HELM, "department"), [("eq", "Information Technology")])

    def test_fuzzy_split(self):
        self.assertEqual(fuzzy_comparisons(EM_FRAGMENT, "department"), [("contains", "Engineer")])
        self.assertEqual(exact_literals(EM_FRAGMENT, "department"), [("ne", "Contractor")])


class TestOperatorSemantics(unittest.TestCase):
    def test_contains_case_insensitive(self):
        self.assertTrue(op_matches("contains", "eng", "Software Eng"))
        self.assertFalse(op_matches("contains", "Engineer", "Hardware Eng"))

    def test_ne_true_on_null(self):
        # The 2026-08-24 null-inversion gotcha: -ne "X" is TRUE for null.
        self.assertTrue(op_matches("ne", "Intern", None))

    def test_match_set_over_census(self):
        census = {"Quality Engineering", "Engineering", "IT Engineering", "Quality"}
        self.assertEqual(match_set("contains", "Engineer", census),
                         {"Quality Engineering", "Engineering", "IT Engineering"})


class TestMatchSetDelta(unittest.TestCase):
    def test_full_census_prevents_dead_clause_verdict(self):
        """The 78-vs-13 incident: 'Engineering' stays matched, so the clause is
        NOT dead; only 'Quality Engineering' leaves the match-set."""
        census = {"Quality Engineering", "Engineering", "Software", "Quality"}
        deltas = match_set_delta(EM_FRAGMENT, "department",
                                 {"Quality Engineering": "Quality"}, census)
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0]["lost"], ["Quality Engineering"])
        self.assertEqual(deltas[0]["gained"], [])

    def test_gained_values(self):
        census = {"Software", "Engineering"}
        deltas = match_set_delta(EM_FRAGMENT, "department",
                                 {"Software": "Software Eng"}, census)
        # 'Software Eng' does NOT contain 'Engineer' -> no gain on this clause
        self.assertEqual(deltas, [])

    def test_no_change_yields_empty(self):
        self.assertEqual(
            match_set_delta(EM_FRAGMENT, "department", {"IT": "Information Technology"},
                            {"Engineering", "IT"}), [])


class TestRewrite(unittest.TestCase):
    def test_literal_swap_ignores_superstrings(self):
        rule = '(user.department -eq "Software") or (user.department -eq "Software Eng")'
        out = rewrite_exact_literals(rule, {"Software": "Software Eng"})
        # both clauses now read "Software Eng" — exactly 2 occurrences, no mangling
        self.assertEqual(out.count('"Software Eng"'), 2)
        self.assertEqual(out.count('"Software"'), 0)

    def test_trailing_hotfix_consolidates_into_guarded_form(self):
        rename = {"Software": "Software Eng"}
        out = dedupe_duplicate_or_clauses(
            rewrite_exact_literals(HOTFIXED_TRAILING, rename),
            "department", hotfix_eligible_values(HOTFIXED_TRAILING, rename))
        expected = GUARDED.replace('"Software"', '"Software Eng"')
        self.assertEqual(out, expected)

    def test_in_paren_hotfix_dedupes_one_clause(self):
        rename = {"Hardware Engineering": "Hardware Eng",
                  "Mech Eng": "Mechanical Eng",
                  "Elec Eng": "Electrical Eng"}
        out = dedupe_duplicate_or_clauses(
            rewrite_exact_literals(HW_IN_PAREN, rename),
            "department", hotfix_eligible_values(HW_IN_PAREN, rename))
        # exactly ONE "Hardware Eng" clause survives; guards untouched
        self.assertEqual(out.count('"Hardware Eng"'), 1)
        self.assertEqual(out.count('"Mechanical Eng"'), 1)
        self.assertEqual(out.count('"Electrical Eng"'), 1)
        self.assertEqual(out.count("employeeId"), 1)

    def test_dedupe_never_loops_forever_on_unstrippable_duplicate(self):
        # duplicate -eq literals joined by AND (not a strippable or-clause)
        rule = '(user.department -eq "X") and (user.department -eq "X")'
        self.assertEqual(dedupe_duplicate_or_clauses(rule, "department", {"X"}), rule)


# Engineering Milestones post-fix (verbatim shape): "Quality" appears TWICE on
# purpose — once in the PM clause, once in the manager clause. The 2026-08-29
# probe incident: an unconditional dedupe stripped the manager clause in a
# production PATCH under a rename that did not even touch this rule.
EM_TWO_QUALITY = ('(user.accountEnabled -eq true) and (((user.department -contains "Engineer") '
                  'or (user.department -eq "Quality") or (user.department -eq "Hardware Eng")) '
                  'and (user.jobTitle -contains "Project Manager")) or '
                  '((user.extensionAttribute1 -eq "Manager") and ((user.department -contains "Eng") '
                  'or (user.department -eq "Quality") or (user.department -eq "Navarc")))')


class TestIncident20260829(unittest.TestCase):
    def test_untouched_rule_is_never_rewritten(self):
        """THE incident: a rename matching nothing in the rule must yield
        skip_clean — dedupe must never run on an untouched rule."""
        plan = build_rewrite_plan(
            [{"id": "em", "displayName": "EM", "membershipRule": EM_TWO_QUALITY}],
            "department", {"ZZ-Probe-NoSuchValue": "ZZ-Probe-Target"})
        self.assertEqual(plan[0]["action"], "skip_clean")
        self.assertIsNone(plan[0]["after"])

    def test_legit_rename_of_twice_used_value_preserves_both_clauses(self):
        """Renaming a value that INTENTIONALLY appears twice must swap both
        occurrences and strip neither (the duplication predates the rename)."""
        plan = build_rewrite_plan(
            [{"id": "em", "displayName": "EM", "membershipRule": EM_TWO_QUALITY}],
            "department", {"Quality": "QA"})
        self.assertEqual(plan[0]["action"], "patch")
        self.assertEqual(plan[0]["after"].count('"QA"'), 2)
        self.assertEqual(plan[0]["after"].count('"Quality"'), 0)

    def test_hotfix_eligibility(self):
        rename = {"Software": "Software Eng"}
        self.assertEqual(hotfix_eligible_values(HOTFIXED_TRAILING, rename), {"Software Eng"})
        self.assertEqual(hotfix_eligible_values(GUARDED, rename), set())
        self.assertEqual(hotfix_eligible_values(EM_TWO_QUALITY, {"Quality": "QA"}), set())


class TestBuildRewritePlan(unittest.TestCase):
    RENAME = {"Software": "Software Eng"}

    def test_plan_actions(self):
        groups = [
            {"id": "1", "displayName": "stale", "membershipRule": GUARDED},
            {"id": "2", "displayName": "clean",
             "membershipRule": '(user.department -eq "Quality") and (user.accountEnabled -eq true)'},
            {"id": "3", "displayName": "hotfixed", "membershipRule": HOTFIXED_TRAILING},
        ]
        plan = build_rewrite_plan(groups, "department", self.RENAME)
        actions = {x["displayName"]: x["action"] for x in plan}
        self.assertEqual(actions, {"stale": "patch", "clean": "skip_clean", "hotfixed": "patch"})
        by_name = {x["displayName"]: x for x in plan}
        self.assertEqual(by_name["stale"]["after"], GUARDED.replace('"Software"', '"Software Eng"'))
        self.assertIsNone(by_name["clean"]["after"])
        # hotfixed collapses to the guarded single-clause form
        self.assertEqual(by_name["hotfixed"]["after"], GUARDED.replace('"Software"', '"Software Eng"'))

    def test_unrewritable_duplicate_flags_manual_review(self):
        rule = '(user.department -eq "Software Eng") and (user.department -eq "Software Eng")'
        # duplicate literal, AND-joined (not strippable), and a stale literal via rename target...
        # construct genuinely stale-but-unrewritable: stale literal whose swap creates
        # an AND-joined duplicate that dedupe cannot strip
        rule = '(user.department -eq "Software") and (user.department -eq "Software")'
        plan = build_rewrite_plan([{"id": "x", "displayName": "dup", "membershipRule": rule}],
                                  "department", self.RENAME)
        # the literal swap DOES change the rule, so this is a patch (both clauses swap);
        # dedupe leaves the AND-joined duplicate in place rather than corrupting structure
        self.assertEqual(plan[0]["action"], "patch")
        self.assertEqual(plan[0]["after"].count('"Software Eng"'), 2)

    def test_empty_rule_is_clean(self):
        plan = build_rewrite_plan([{"id": "x", "displayName": "norule", "membershipRule": None}],
                                  "department", self.RENAME)
        self.assertEqual(plan[0]["action"], "skip_clean")


class TestTopLevelOrDefect(unittest.TestCase):
    def test_dynamic_it_defect_detected(self):
        self.assertTrue(top_level_or_defect(DYNAMIC_IT))

    def test_hotfixed_trailing_or_detected(self):
        self.assertTrue(top_level_or_defect(HOTFIXED_TRAILING))

    def test_guarded_rule_clean(self):
        self.assertFalse(top_level_or_defect(GUARDED))

    def test_parenthesized_or_group_clean(self):
        self.assertFalse(top_level_or_defect(HW_IN_PAREN))

    def test_hyphenated_joiners_at_top_level(self):
        # Helm's -and joins parenthesized groups; the -or is INSIDE parens -> clean
        self.assertFalse(top_level_or_defect(HELM))

    def test_or_inside_quoted_string_ignored(self):
        rule = '(user.department -eq "Sales or Marketing") and (user.accountEnabled -eq true)'
        self.assertFalse(top_level_or_defect(rule))


if __name__ == "__main__":
    unittest.main()
