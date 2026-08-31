# Plan: Malformed — structure-critical headings at the wrong level

Demo: parse_plan.py must reject this plan (setup exit code 20, parse-failed)

This fixture violates the heading-level contract in superplan's Plan
Structure Template (references/planning-framework.md): the Falsifiers
section is authored at H1 instead of the mandated H2, and the Metric
Commands section at H2 instead of the mandated H3. Both sections are
therefore invisible to supergoal's parser, which must refuse the plan
at setup time rather than start a loop with no falsifiers and no metric.

## Goal

Look plausible to a human reader while violating the structure contract.

# Falsifiers

- [F-h1] this item is invisible to the parser: the Falsifiers heading must be H2 or deeper, not H1

## Metric Commands

```bash
echo "METRIC NEVER_EXTRACTED=1"
```
